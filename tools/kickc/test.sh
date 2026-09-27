#!/usr/bin/env bash
# test.sh — smoke-test kickc (noarch/JVM) in $PREFIX (spec §6.3)
# Verified against upstream 0.8.6: -V prints the version, -p selects the
# target platform, output is <name>.asm next to the source.
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(kickc): $*" >&2; exit 1; }

command -v java >/dev/null || fail "java not on PATH (runtime requirement: java>=11)"
[ -x "$BIN/kickc" ] || fail "missing or not executable: $BIN/kickc"

# -V is kickc's version flag ("KickC <version> BETA", exit 0).
"$BIN/kickc" -V >/dev/null || fail "kickc -V failed"

# End-to-end compile from an arbitrary cwd (spec §6.3): compile a copy in a
# temp dir so outputs never pollute fixtures/.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
cp "$FIXTURES/hello.c" .
"$BIN/kickc" -p c64 hello.c || fail "kickc -p c64 hello.c failed"
[ -s hello.asm ] || fail "hello.asm missing or empty"

echo "test.sh(kickc): OK"
