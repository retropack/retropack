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
    args = p.parse_args(argv)
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
    so anchored file_regexes can match regardless of the path around them."""
    cands = []
    try:
        cands += _json_strings(json.loads(best_release_json))
    except json.JSONDecodeError:
        pass
    cands += re.findall(r"<title>(.*?)</title>", rss_xml, re.S)
    return [os.path.basename(c.strip()) for c in cands]


def pick_latest(versions: list[str], min_version: str = "0.0",
                skip_versions: list[str] | None = None) -> str | None:
    """Newest version, honoring min_version / skip_versions (spec §5)."""
    skip = set(skip_versions or [])
    ok = [v for v in versions
          if v not in skip and compare_versions(v, min_version) >= 0]
    return max(ok, key=cmp_to_key(compare_versions)) if ok else None


def _http(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "retropack-watch"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def latest_version(tool: str) -> str | None:
    """Newest upstream version of `tool` matching its tool.toml constraints."""
    manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", tool, "tool.toml")
    with open(manifest, "rb") as f:
        cfg = tomllib.load(f)
    up = cfg["upstream"]
    if up["type"] == "github":
        out = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs",
             f"https://github.com/{up['repo']}.git"],
            capture_output=True, text=True, check=True, timeout=60).stdout
        versions = parse_lsremote(out, up["tag_regex"])
    elif up["type"] == "gitlab":
        out = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs",
             f"https://gitlab.com/{up['repo']}.git"],
            capture_output=True, text=True, check=True, timeout=60).stdout
        versions = parse_lsremote(out, up["tag_regex"])
    elif up["type"] == "sourceforge":
        project = up["repo"]
        candidates = parse_sourceforge(
            _http(f"https://sourceforge.net/projects/{project}/best_release.json"),
            _http(f"https://sourceforge.net/projects/{project}/rss?path=/"))
        versions = parse_tags(candidates, up["file_regex"])
    else:
        raise ValueError(f"unknown upstream type: {up['type']}")
    return pick_latest(versions, up.get("min_version", "0.0"),
                       up.get("skip_versions"))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
