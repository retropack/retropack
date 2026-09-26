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

curl -fsSL -o "$ARCHIVE" "$SRC_URL"

# Detect format by magic bytes, not URL suffix: SourceForge download URLs end
# in `/download`, not `.zip` (spec §10 tass64).
MAGIC="$(head -c 2 "$ARCHIVE" | od -An -tx1 | tr -d ' \n')"
case "$MAGIC" in
  504b*)                              # PK…
    [ "$STRIP" = "0" ] || { echo "fetch-source: zip archives only supported with strip_components = 0" >&2; exit 1; }
    unzip -q -o "$ARCHIVE" -d "$SRC"
    ;;
  1f8b*)                              # gzip
    tar -xzf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
  *)
    echo "fetch-source: unrecognized archive format for $SRC_URL (magic $MAGIC)" >&2
    exit 1
    ;;
esac

if [ -d "$REPO_ROOT/tools/$TOOL/patches" ]; then
  for p in "$REPO_ROOT/tools/$TOOL/patches"/*; do
    [ -e "$p" ] || continue
    patch -d "$SRC" -p1 < "$p"
  done
fi

echo "fetch-source: SRC=$SRC"
