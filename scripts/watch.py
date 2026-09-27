#!/usr/bin/env python3
"""watch.py — upstream/released diff + dispatch (spec §8.1).

Stdlib only. Pure logic (parsing, version compare, pending selection,
latest-version resolution) is implemented and tested; network fetch +
repository_dispatch land in M1.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
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


def detect(tool_filter: str | None = None,
           force_version: str | None = None) -> dict[str, list[str]]:
    """The spec §8.1 algorithm: {tool: [versions to dispatch]}.

    force_version bypasses the released/blocked checks but still honors the
    manifest's min_version/skip_versions policy (spec §8.2's forced input).
    """
    if force_version and not tool_filter:
        raise ValueError("--version forces a build within a single --tool")
    pending_all: dict[str, list[str]] = {}
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
            pending = versions[:cap]
        else:
            released = released_from_api(
                _github_get(f"/repos/retropack/{name}/releases?per_page=100"))
            blocked = blocked_from_issues(
                _github_get(f"/repos/retropack/{name}/issues?labels=build-failure&state=open"),
                name)
            pending = select_pending(versions, released, blocked, cap)
        if pending:
            pending_all[name] = pending
    return pending_all


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
    p.add_argument("--detect", action="store_true",
                   help="print pending {tool: [versions]} JSON (spec §8.1) and exit")
    args = p.parse_args(argv)
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
