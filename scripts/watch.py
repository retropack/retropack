#!/usr/bin/env python3
"""watch.py — upstream/released diff, source-hash pins + dispatch (spec §8.1).

Stdlib only. Pending versions split at the review gate: pinned ones are
dispatchable; unpinned ones are downloaded (never extracted/executed) and
hashed for a pins PR — the human merge is the pipeline's trust root.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
from functools import cmp_to_key


def parse_tags(tags: list[str], pattern: str) -> list[str]:
    """Extract the `version` named group from each tag matching pattern.

    Non-matching tags are dropped. A pattern without a `version` group is a
    manifest error and raises ValueError.
    """
    rx = re.compile(pattern)
    if "version" not in rx.groupindex:
        # Review Focus: a bad manifest must not abort the daily run for all
        # tools — skip this tool's versions instead (schema test catches it at PR time).
        print(f"watch: skipping pattern without 'version' group: {pattern!r}", file=sys.stderr)
        return []
    out = []
    for tag in tags:
        m = rx.match(tag)
        if m:
            out.append(m.group("version"))
    return out


def _segments(version: str) -> list:
    return [int(p) if p.isdigit() else p for p in version.split(".")]


def compare_versions(a: str, b: str) -> int:
    """Lenient numeric-dotted comparison (spec §5).

    Split on '.' and compare positionally. Missing segments pad as 0, so
    '2.19.0' == '2.19' and '2.19' < '2.19.1'. Numeric segments compare as
    ints, non-numeric as strings; a non-numeric segment beats a missing
    (padded) one, so '2.19rc1' > '2.19'.
    """
    sa, sb = _segments(a), _segments(b)
    for i in range(max(len(sa), len(sb))):
        x = sa[i] if i < len(sa) else 0
        y = sb[i] if i < len(sb) else 0
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return 1 if x > y else -1
        if isinstance(x, str) and isinstance(y, str):
            return 1 if x > y else -1
        # mixed: real non-numeric segment beats a padded 0
        return 1 if isinstance(x, str) else -1
    return 0


def select_pending(upstream: list[str], released: list[str], blocked: list[str],
                   max_per_run: int) -> list[str]:
    """upstream − released − blocked, newest first, capped at max_per_run (spec §8.1).

    Released/blocked matching uses compare_versions equality, so equivalent
    forms ("2.19" vs "2.19.0") block each other (spec §5).
    """
    taken = list(dict.fromkeys(list(released) + list(blocked)))
    pending = [v for v in set(upstream)
               if not any(compare_versions(v, t) == 0 for t in taken)]
    pending.sort(key=cmp_to_key(compare_versions), reverse=True)
    return pending[:max_per_run]


def latest_flag(version: str, releases: list[dict]) -> str:
    """"true"/"false": is `version` the highest PUBLISHED release? (spec §7.4
    step 6 — backfilling older versions must not steal "latest").
    """
    published = [r["tag_name"][1:] for r in releases
                 if not r.get("draft") and not r.get("prerelease", False)
                 and r["tag_name"].startswith("v")]
    highest = all(compare_versions(version, v) >= 0
                  for v in published if v != version)
    return "true" if highest else "false"


def highest_release_id(releases_json: str) -> str:
    """id of the highest PUBLISHED release (drafts/prereleases excluded),
    empty when none. Needed because GitHub's `make_latest=false` only
    UNMARKS: an unmarked release then falls back to the default (newest
    created) — which for a backfill is always the backfill itself — so the
    true highest must be explicitly pinned `true` (verified live on
    retropack/tass64).
    """
    data = json.loads(releases_json) if isinstance(releases_json, str) else releases_json
    published = [r for r in data
                 if not r.get("draft") and not r.get("prerelease", False)
                 and r.get("tag_name", "").startswith("v")]
    if not published:
        return ""
    best = max(published, key=cmp_to_key(
        lambda a, b: compare_versions(a["tag_name"][1:], b["tag_name"][1:])))
    return str(best.get("id", ""))


def release_asset_url(releases_json: str, tag: str, link_name: str) -> str:
    """Pick a named asset link's URL for `tag` from a GitLab releases JSON
    document (kickc's distribution zip lives behind a release asset link).
    Raises ValueError when the release or link is missing — the caller
    (fetch-source) turns that into a loud build failure.
    """
    for rel in json.loads(releases_json):
        if rel.get("tag_name") == tag:
            for link in (rel.get("assets") or {}).get("links") or []:
                if link.get("name") == link_name and link.get("url"):
                    return link["url"]
            raise ValueError(
                f"release {tag} has no asset link named {link_name!r}")
    raise ValueError(f"no upstream release for tag {tag}")


def released_from_api(releases_json: str) -> list[str]:
    """Published (non-draft, non-prerelease) release versions, v stripped
    (spec §8.1: 'released' side of the diff)."""
    out = []
    for r in json.loads(releases_json):
        if r.get("draft") or r.get("prerelease"):
            continue
        tag = r.get("tag_name", "")
        out.append(tag[1:] if tag.startswith("v") else tag)
    return out


def blocked_from_issues(issues_json: str, tool: str) -> list[str]:
    """Versions named in OPEN build-failure issues of `tool` (spec §8.1:
    closing the issue = retry). Titles: 'build failure: <tool> <version>' and
    'acceptance failure: <tool> <version>' — same label either way. Pull
    requests are excluded even though the API mixes them into /issues."""
    out = []
    for issue in json.loads(issues_json):
        if "pull_request" in issue:
            continue
        title = issue.get("title", "")
        for kind in ("build failure", "acceptance failure"):
            prefix = f"{kind}: {tool} "
            if title.startswith(prefix):
                out.append(title[len(prefix):].strip())
                break
    return out


def _github_get(path: str) -> str:
    """GET api.github.com with the ambient GITHUB_TOKEN when present (the
    detect job's read-only token); unauthenticated fallback works for public
    repos (and stays well under the 60/hr limit for a daily run)."""
    headers = {"User-Agent": "retropack-watch",
               "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request("https://api.github.com" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# --- source-hash pins: the §8.1 review gate ---

def resolve_source_url(cfg: dict, version: str) -> str:
    """Download URL for one version: the manifest's {version} template, or
    the GitLab release asset link for repackage mode (kickc's distribution
    zip lives behind a per-version release link — spec §10). fetch-source.sh
    shells out to this (--source-url) so watcher hashes and build downloads
    can never resolve differently."""
    src = cfg["source"]
    # section itself is optional — mode defaults to "source" (spec §5 example
    # marks [build] fields optional; a missing section must not traceback)
    if cfg.get("build", {}).get("mode", "source") != "repackage":
        return src["url"].replace("{version}", version)
    up = cfg["upstream"]
    if up["type"] != "gitlab":
        raise ValueError(f"repackage mode only supports gitlab upstream (got {up['type']})")
    project = urllib.parse.quote(up["repo"], safe="")
    req = urllib.request.Request(
        f"https://gitlab.com/api/v4/projects/{project}/releases",
        headers={"User-Agent": "retropack-fetch"})
    releases = urllib.request.urlopen(req, timeout=30).read().decode()
    return release_asset_url(releases, version, src.get("release_asset", "Binary"))


class _HTTPSOnly(urllib.request.HTTPRedirectHandler):
    """Refuse protocol-downgrade redirects: these digests land in the
    reviewed pins file, so a poisoned fetch here corrupts the trust root
    itself, not just one build."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError(f"refusing non-https redirect: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_sha256(url: str) -> str:
    """sha256 of the archive at `url`. HTTPS-only, initial request and every
    redirect (kickc's shortener → wiki chain stays https). Streamed straight
    into the digest — the watcher never extracts or executes what it hashes,
    so this is safe to run with a read-only token on attacker-sized input."""
    if not url.startswith("https://"):
        raise ValueError(f"refusing non-https source url: {url}")
    opener = urllib.request.build_opener(_HTTPSOnly)
    req = urllib.request.Request(url, headers={"User-Agent": "retropack-watch"})
    h = hashlib.sha256()
    with opener.open(req, timeout=60) as r:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pins_path(tool: str, tools_dir: str | None = None) -> str:
    return os.path.join(tools_dir or _TOOLS_DIR, tool, "source-sha256.txt")


def pinned_versions(tool: str) -> set[str]:
    """Versions with a reviewed source-hash pin. No file → nothing pinned:
    the watcher proposes instead of dispatching, and fetch-source.sh stays
    permissive until the file first exists — that merge gates the tool."""
    try:
        with open(_pins_path(tool)) as f:
            return {ln.split()[1] for ln in f
                    if ln.strip() and not ln.startswith("#")}
    except FileNotFoundError:
        return set()


def write_pins(propose: dict, only_tool: str | None, body_dir: str,
               tools_dir: str | None = None) -> list[str]:
    """Append propose hashes to tools/<tool>/source-sha256.txt (idempotent)
    and write the PR review body to body_dir/<tool>.md. Returns tools touched."""
    root = tools_dir or _TOOLS_DIR
    os.makedirs(body_dir, exist_ok=True)
    touched = []
    for tool, versions in sorted(propose.items()):
        if only_tool and tool != only_tool:
            continue
        path = _pins_path(tool, root)
        lines = []
        if os.path.exists(path):
            lines = open(path).read().splitlines()
        have = {ln.split()[1] for ln in lines if ln.strip() and not ln.startswith("#")}
        new = [(v, versions[v]) for v in sorted(versions) if v not in have]
        if not new:
            continue
        if not lines:
            lines = ["# Reviewed source-archive hashes (spec §8.1 review gate): '<sha256>  <version>'.",
                     "# fetch-source.sh refuses to build a version missing from this file; the",
                     "# watcher dispatches a new version only after its pin PR merges."]
        lines += [f"{meta['sha256']}  {v}" for v, meta in new]
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        rows = "\n".join(f"| `{v}` | `{meta['sha256']}` | {meta['url']} |"
                         for v, meta in new)
        body = "\n".join([
            f"## Source-hash pins: {tool}",
            "",
            "The watcher found new upstream version(s) and hashed the source archives",
            "it would build (download only — nothing was extracted or executed).",
            "Review = reproduce a hash locally and compare:",
            "",
            f"    python3 scripts/watch.py --source-sha256 {tool} <version>",
            "",
            "| version | sha256 | source |",
            "| --- | --- | --- |",
            rows,
            "",
            f"Merging appends these pins to `tools/{tool}/source-sha256.txt`; the next",
            "watch run dispatches the build. Once the file exists, `fetch-source.sh`",
            "refuses to build a version missing from it — the merge is the gate.",
            "",
        ])
        with open(os.path.join(body_dir, f"{tool}.md"), "w") as f:
            f.write(body)
        touched.append(tool)
    return touched


def detect(tool_filter: str | None = None,
           force_version: str | None = None) -> dict:
    """The spec §8.1 algorithm, split at the review gate:
    {"dispatch": {tool: [pinned versions]}, "propose": {tool: {version:
    {sha256, url}}}}.

    force_version bypasses the released/blocked checks AND the pin gate (a
    maintainer forcing a build IS the review checkpoint; fetch-source.sh
    still enforces pins for gated tools) but honors the manifest's
    min_version/skip_versions policy (spec §8.2's forced input).
    """
    if force_version and not tool_filter:
        raise ValueError("--version forces a build within a single --tool")
    dispatch: dict[str, list[str]] = {}
    propose: dict[str, dict[str, dict[str, str]]] = {}
    for name in sorted(os.listdir(_TOOLS_DIR)):
        if name.startswith("_"):
            continue
        if not os.path.isfile(os.path.join(_TOOLS_DIR, name, "tool.toml")):
            continue
        if tool_filter and name != tool_filter:
            continue
        cfg = _load_manifest(name)
        up = cfg["upstream"]
        cap = int(up.get("max_per_run", 10))
        raw = [force_version] if force_version else upstream_versions(name, cfg)
        versions = eligible(raw, up.get("min_version", "0.0"),
                            up.get("skip_versions"))
        if force_version:
            if versions:
                dispatch[name] = versions[:cap]
            continue
        released = released_from_api(
            _github_get(f"/repos/retropack/{name}/releases?per_page=100"))
        blocked = blocked_from_issues(
            _github_get(f"/repos/retropack/{name}/issues?labels=build-failure&state=open"),
            name)
        pending = select_pending(versions, released, blocked, cap)
        if not pending:
            continue
        pins = pinned_versions(name)
        ready = [v for v in pending if v in pins]
        if ready:
            dispatch[name] = ready
        # ponytail: unmerged pins get re-hashed every run until merge
        # (idempotent force-push); dedupe via PR-query if download size matters
        for v in [v for v in pending if v not in pins]:
            try:
                url = resolve_source_url(cfg, v)
                propose.setdefault(name, {})[v] = {
                    "sha256": fetch_sha256(url), "url": url}
            except Exception as e:  # one bad download must not block other tools
                print(f"watch: {name} {v}: hash fetch failed: {e}", file=sys.stderr)
    return {"dispatch": dispatch, "propose": propose}


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="watch.py", description="detect missing (tool, version) pairs")
    p.add_argument("--tool", help="limit to one tool")
    p.add_argument("--version", help="force a specific version (bypasses released/blocked)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--latest-for", metavar="TOOL",
                   help="print the newest matching upstream version and exit")
    p.add_argument("--latest-flag", metavar="VERSION",
                   help="read a releases JSON array on stdin; print true if "
                        "VERSION is the highest published release (spec §7.4)")
    p.add_argument("--highest-id", action="store_true",
                   help="read a releases JSON array on stdin; print the id of "
                        "the highest published release (empty if none)")
    p.add_argument("--detect", action="store_true",
                   help="print {\"dispatch\": ..., \"propose\": ...} JSON (spec §8.1) and exit")
    p.add_argument("--source-url", nargs=2, metavar=("TOOL", "VERSION"),
                   help="print the resolved download URL (fetch-source.sh uses this)")
    p.add_argument("--source-sha256", nargs=2, metavar=("TOOL", "VERSION"),
                   help="print '<sha256>  VERSION' — for reviewing/hand-adding pins")
    p.add_argument("--write-pins", nargs="?", const="", metavar="TOOL",
                   help="read propose JSON on stdin; append pins + write PR body "
                        "(--body-dir) for TOOL, or all tools when omitted")
    p.add_argument("--body-dir", metavar="DIR", help="PR body output dir for --write-pins")
    args = p.parse_args(argv)
    if args.source_url:
        tool, version = args.source_url
        print(resolve_source_url(_load_manifest(tool), version))
        return 0
    if args.source_sha256:
        tool, version = args.source_sha256
        print(f"{fetch_sha256(resolve_source_url(_load_manifest(tool), version))}  {version}")
        return 0
    if args.write_pins is not None:
        if not args.body_dir:
            p.error("--write-pins needs --body-dir")
        print(" ".join(write_pins(json.load(sys.stdin), args.write_pins or None,
                                  args.body_dir)))
        return 0
    if args.highest_id:
        print(highest_release_id(json.load(sys.stdin)))
        return 0
    if args.detect:
        try:
            pending = detect(args.tool, args.version)
        except Exception as e:  # network/manifest errors → clear CLI failure
            print(f"watch: {e}", file=sys.stderr)
            return 1
        print(json.dumps(pending, sort_keys=True))
        return 0
    if args.latest_flag:
        print(latest_flag(args.latest_flag, json.load(sys.stdin)))
        return 0
    if args.latest_for:
        try:
            v = latest_version(args.latest_for)
        except Exception as e:  # network/manifest errors → clear CLI failure
            print(f"watch: {e}", file=sys.stderr)
            return 1
        if v is None:
            print(f"watch: no matching upstream version for {args.latest_for}",
                  file=sys.stderr)
            return 1
        print(v)
        return 0
    print("TODO: fetch + dispatch (M1)")
    return 0


# --- latest-version resolution (used by scripts/local-build.sh) ---

def parse_lsremote(text: str, pattern: str) -> list[str]:
    """Tag names out of `git ls-remote --tags --refs` output → versions."""
    tags = [line.split("refs/tags/", 1)[1]
            for line in text.splitlines() if "refs/tags/" in line]
    return parse_tags(tags, pattern)


def _json_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _json_strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _json_strings(v)]
    return []


def parse_sourceforge(best_release_json: str, rss_xml: str) -> list[str]:
    """Candidate filenames from best_release.json + RSS (spec §8.1), basenamed
    so anchored file_regexes can match regardless of the path around them.
    Real SF RSS wraps titles in <![CDATA[/path/file.zip]]> — unwrap first."""
    cands = []
    try:
        cands += _json_strings(json.loads(best_release_json))
    except json.JSONDecodeError:
        pass
    for title in re.findall(r"<title>(.*?)</title>", rss_xml, re.S):
        t = title.strip()
        if t.startswith("<![CDATA[") and t.endswith("]]>"):
            t = t[len("<![CDATA["):-len("]]>")].strip()
        cands.append(t)
    return [os.path.basename(c) for c in cands if c]


def pick_latest(versions: list[str], min_version: str = "0.0",
                skip_versions: list[str] | None = None) -> str | None:
    """Newest version, honoring min_version / skip_versions (spec §5)."""
    ok = eligible(versions, min_version, skip_versions)
    return max(ok, key=cmp_to_key(compare_versions)) if ok else None


def eligible(versions: list[str], min_version: str = "0.0",
             skip_versions: list[str] | None = None) -> list[str]:
    """Versions passing the manifest's min_version / skip_versions policy
    (spec §5), input order preserved — detect() applies it to every pending
    candidate, not just the newest one."""
    skip = set(skip_versions or [])
    return [v for v in versions
            if v not in skip and compare_versions(v, min_version) >= 0]


def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "retropack-watch"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


_TOOLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _load_manifest(tool: str) -> dict:
    with open(os.path.join(_TOOLS_DIR, tool, "tool.toml"), "rb") as f:
        return tomllib.load(f)


def upstream_versions(tool: str, cfg: dict | None = None) -> list[str]:
    """All upstream versions matching the manifest's regex (spec §8.1
    adapters): git ls-remote for github/gitlab, best_release + RSS for
    SourceForge (root AND /source — the root feed lists no files for some
    projects, which would silently cap backfill)."""
    cfg = cfg or _load_manifest(tool)
    up = cfg["upstream"]
    if up["type"] in ("github", "gitlab"):
        host = "github.com" if up["type"] == "github" else "gitlab.com"
        out = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs",
             f"https://{host}/{up['repo']}.git"],
            capture_output=True, text=True, check=True, timeout=60).stdout
        return parse_lsremote(out, up["tag_regex"])
    if up["type"] == "sourceforge":
        project = up["repo"]
        candidates = parse_sourceforge(
            _http(f"https://sourceforge.net/projects/{project}/best_release.json"),
            _http(f"https://sourceforge.net/projects/{project}/rss?path=/"))
        candidates += parse_sourceforge(
            "{}", _http(f"https://sourceforge.net/projects/{project}/rss?path=/source"))
        return parse_tags(candidates, up["file_regex"])
    raise ValueError(f"unknown upstream type: {up['type']}")


def latest_version(tool: str) -> str | None:
    """Newest upstream version of `tool` matching its tool.toml constraints."""
    cfg = _load_manifest(tool)
    up = cfg["upstream"]
    return pick_latest(upstream_versions(tool, cfg),
                       up.get("min_version", "0.0"), up.get("skip_versions"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
