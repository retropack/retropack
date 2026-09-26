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

read -r SRC_URL STRIP <<EOF
$(python3 - "$MANIFEST" "$VERSION" <<'PY'
import tomllib, sys
manifest, version = sys.argv[1], sys.argv[2]
t = tomllib.loads(open(manifest, "rb").read())
print(t["source"]["url"].replace("{version}", version), t["source"].get("strip_components", 1))
PY
)
EOF

SRC="${SRC:-$WORK/src}"
mkdir -p "$WORK" "$SRC"
ARCHIVE="$WORK/src-archive"

case "$SRC_URL" in
  *.zip) ARCHIVE="$ARCHIVE.zip" ;;
  *)     ARCHIVE="$ARCHIVE.tar.gz" ;;
esac

curl -fsSL -o "$ARCHIVE" "$SRC_URL"

case "$ARCHIVE" in
  *.zip)
    [ "$STRIP" = "0" ] || { echo "fetch-source: zip archives only supported with strip_components = 0" >&2; exit 1; }
    unzip -q -o "$ARCHIVE" -d "$SRC"
    ;;
  *)
    tar -xzf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
esac

if [ -d "$REPO_ROOT/tools/$TOOL/patches" ]; then
  for p in "$REPO_ROOT/tools/$TOOL/patches"/*; do
    [ -e "$p" ] || continue
    patch -d "$SRC" -p1 < "$p"
  done
fi

echo "fetch-source: SRC=$SRC"
