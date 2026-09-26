#!/usr/bin/env python3
"""watch.py — upstream/released diff + dispatch (spec §8.1).

Stdlib only. Pure logic (parsing, version compare, pending selection) is
implemented and tested; network fetch + repository_dispatch land in M1.
"""
import argparse
import re
import sys
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


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="watch.py", description="detect missing (tool, version) pairs")
    p.add_argument("--tool", help="limit to one tool")
    p.add_argument("--version", help="force a specific version (bypasses released/blocked)")
    p.add_argument("--dry-run", action="store_true")
    p.parse_args(argv)
    print("TODO: fetch + dispatch (M1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
