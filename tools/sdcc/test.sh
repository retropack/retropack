#!/usr/bin/env bash
# test.sh — smoke-test sdcc in $PREFIX (spec §6.3, §10); runs from an arbitrary
# cwd to prove relocatable include/lib lookup (spec §13).
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(sdcc): $*" >&2; exit 1; }

for b in sdcc sdcpp sdasz80 sdldz80; do
  [ -x "$BIN/$b" ] || fail "missing or not executable: $BIN/$b"
done

"$BIN/sdcc" --version >/dev/null || fail "sdcc --version failed"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
"$BIN/sdcc" -mz80 -c "$FIXTURES/hello.c" || fail "sdcc -mz80 compile failed"
"$BIN/sdcc" -mmos6502 -c "$FIXTURES/hello.c" || fail "sdcc -mmos6502 compile failed"
[ -s hello.rel ] || [ -s hello.o ] || fail "compiled object missing or empty"

# sdasz80/sdldz80 round-trip (spec §10).
echo '        .module m' > tiny.s
"$BIN/sdasz80" -o tiny.s || fail "sdasz80 failed"
"$BIN/sdldz80" -i tiny || fail "sdldz80 failed"

echo "test.sh(sdcc): OK"
