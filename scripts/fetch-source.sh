#!/usr/bin/env bash
# fetch-source.sh — download + verify + extract source per tools/<tool>/tool.toml (spec §5, §6.1)
# Steps: read tool.toml → substitute {version} in source.url → download →
# extract with strip_components → apply tools/<tool>/patches/* in order (-p1).
set -euo pipefail

: "${TOOL:?TOOL must be set}"
: "${VERSION:?VERSION must be set}"
: "${WORK:?WORK must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/tools/$TOOL/tool.toml"
[ -f "$MANIFEST" ] || { echo "fetch-source: no manifest $MANIFEST" >&2; exit 1; }

read -r MANIFEST_URL STRIP <<EOF
$(python3 - "$MANIFEST" "$VERSION" <<'PY'
import tomllib, sys
manifest, version = sys.argv[1], sys.argv[2]
t = tomllib.load(open(manifest, "rb"))
print(t["source"]["url"].replace("{version}", version), t["source"].get("strip_components", 1))
PY
)
EOF
# SRC_URL override exists for tests (tests/test_fetch_source.py); production uses the manifest.
SRC_URL="${SRC_URL:-$MANIFEST_URL}"

SRC="${SRC:-$WORK/src}"
mkdir -p "$WORK" "$SRC"
ARCHIVE="$WORK/src-archive"

# HTTPS-only for the initial request and every redirect (spec §5's integrity
# stance hardened against protocol-downgrade redirects); file:// stays
# allowed for the local tests.
curl -fsSL --proto '=https,file' --proto-redir '=https' -o "$ARCHIVE" "$SRC_URL"

# Detect format by magic bytes, not URL suffix: SourceForge download URLs end
# in `/download`, not `.zip` (spec §10 tass64).
MAGIC="$(head -c 2 "$ARCHIVE" | od -An -tx1 | tr -d ' \n')"
case "$MAGIC" in
  504b*)                              # PK…
    unzip -q -o "$ARCHIVE" -d "$SRC"
    # unzip has no --strip-components: strip one level by moving the single
    # top-level dir's contents up. (Ceiling: zips support strip 0/1 only —
    # no current tool needs more.)
    if [ "$STRIP" -ge 1 ]; then
      [ "$STRIP" -le 1 ] || { echo "fetch-source: zip strip_components > 1 unsupported" >&2; exit 1; }
      top=$(find "$SRC" -mindepth 1 -maxdepth 1)
      n=$(printf '%s\n' "$top" | grep -c .)
      if [ "$n" -ne 1 ] || [ ! -d "$top" ]; then
        echo "fetch-source: expected a single top-level dir in zip to strip, found: $top" >&2
        exit 1
      fi
      cp -a "$top"/. "$SRC"/ && rm -rf "$top"
    fi
    ;;
  1f8b*)                              # gzip
    tar -xzf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
  425a*)                              # BZh — sdcc ships .tar.bz2 exclusively
    tar -xjf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
  *)
    echo "fetch-source: unrecognized archive format for $SRC_URL (magic $MAGIC)" >&2
    exit 1
    ;;
esac

if [ -d "$REPO_ROOT/tools/$TOOL/patches" ]; then
  for p in "$REPO_ROOT/tools/$TOOL/patches"/*; do
    [ -e "$p" ] || continue
    if [ -d "$p" ]; then
      # Version-scoped: patches/<version>/ applies ONLY to that exact version
      # (e.g. tass64's memalign rename exists in 1.59.3120 and nowhere else).
      [ "$(basename "$p")" = "$VERSION" ] || continue
      for q in "$p"/*; do
        [ -f "$q" ] || continue
        patch -d "$SRC" -p1 < "$q"
      done
    else
      patch -d "$SRC" -p1 < "$p"
    fi
  done
fi

echo "fetch-source: SRC=$SRC"
