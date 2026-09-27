#!/usr/bin/env bash
# build.sh — kickc (spec §10, mode = repackage): unpack upstream's
# distribution zip into our archive layout + a relocatable POSIX launcher.
# No compilation here — upstream ships prebuilt jars (java ≥ 11 at runtime).
# Env contract (spec §6.1): TOOL VERSION PLATFORM SRC PREFIX …
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"

# SRC is the stripped zip root (fetch-source strips kickc/): verify the
# pieces the launcher needs, then lay them out (examples/ and the PDF manual
# are not runtime needs and stay out of the archive).
# mkdir first: cp -r into a NONEXISTENT destination makes the destination a
# copy of the source (contents land at PREFIX root instead of PREFIX/jar).
mkdir -p "$PREFIX"
for d in jar fragment include lib target; do
  [ -d "$SRC/$d" ] || { echo "build.sh(kickc): missing '$d' in distribution" >&2; exit 1; }
  cp -r "$SRC/$d" "$PREFIX/"
done
# Upstream's third-party notices (bundled jars) — distinct from our
# RETROPACK-NOTICE, which package.sh adds.
[ -f "$SRC/NOTICE.txt" ] && cp "$SRC/NOTICE.txt" "$PREFIX/"

mkdir -p "$PREFIX/bin"
# Relocatable POSIX-sh launcher (spec §7.2). Reproduces upstream's invocation
# contract: KICKC_* env alone is NOT enough — the -F/-I/-L/-P args are
# required (verified empirically: without -P the platform list comes back
# empty). Their bin/kickc.sh needs bash and echoes every command line.
cat > "$PREFIX/bin/kickc" <<'WRAP'
#!/bin/sh
# KickC launcher — resolves its own location; needs a JRE >= 11 on PATH.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
KCHOME=$(dirname "$HERE")
JAR=$(ls "$KCHOME"/jar/kickc-*.jar 2>/dev/null | head -n1)
if [ -z "${JAR:-}" ] || [ ! -f "$JAR" ]; then
  echo "kickc: jar not found under $KCHOME/jar" >&2
  exit 1
fi
if ! command -v java >/dev/null 2>&1; then
  echo "kickc: java not found on PATH (needs a JRE >= 11)" >&2
  exit 1
fi
# shellcheck disable=SC2086  # JAVA_OPTS is intentionally word-split
exec java ${JAVA_OPTS:-} -jar "$JAR" \
  -F "$KCHOME/fragment" -I "$KCHOME/include" \
  -L "$KCHOME/lib" -P "$KCHOME/target" "$@"
WRAP
chmod +x "$PREFIX/bin/kickc"
