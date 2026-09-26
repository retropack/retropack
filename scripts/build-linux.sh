#!/usr/bin/env bash
# build-linux.sh — host-side wrapper: docker run alpine:3 → tools/<tool>/build.sh (spec §6.2)
# Presets inside the container: CC=gcc CXX=g++ CFLAGS="-O2" LDFLAGS="-static".
set -euo pipefail

: "${TOOL:?TOOL must be set}"
: "${VERSION:?VERSION must be set}"
: "${WORK:?WORK must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${SRC:?SRC must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALPINE_PACKAGES="$(python3 - "$REPO_ROOT/tools/$TOOL/tool.toml" <<'PY'
import tomllib, sys
t = tomllib.load(open(sys.argv[1], "rb"))
print(" ".join(t["build"].get("alpine_packages", [])))
PY
)"
NPROC="${NPROC:-$(nproc)}"

docker run --rm -v "$REPO_ROOT:/work/brain" -v "$WORK:/work" -w /work \
  -e TOOL="$TOOL" -e VERSION="$VERSION" -e PLATFORM \
  -e OS -e ARCH -e SRC="$SRC" -e PREFIX="$PREFIX" -e NPROC="$NPROC" \
  -e CC=gcc -e CXX=g++ -e CFLAGS="-O2" -e LDFLAGS="-static" \
  -e ALPINE_PACKAGES="$ALPINE_PACKAGES" \
  alpine:3 sh -c 'apk add --no-cache $ALPINE_PACKAGES && sh /work/brain/tools/$TOOL/build.sh'
