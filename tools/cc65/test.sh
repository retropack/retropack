#!/usr/bin/env bash
# test.sh — smoke-test cc65 in $PREFIX (spec §6.3): expected_bins, --version,
# fixture compile. No network. Works from any path (relocatable, no CC65_HOME).
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
BINS="cc65 ca65 ld65 cl65 ar65 co65 da65 od65 sp65 grc65 sim65"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(cc65): $*" >&2; exit 1; }

unset CC65_HOME || true   # prove relocatable lookup (spec §13)

for b in $BINS; do
  [ -x "$BIN/$b" ] || fail "missing or not executable: $BIN/$b"
done

"$BIN/cl65" --version >/dev/null || fail "cl65 --version failed"

# End-to-end compile from an arbitrary cwd (spec §6.3).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
"$BIN/cl65" -t c64 "$FIXTURES/hello.c" -o hello.prg || fail "cl65 hello.c failed"
[ -s hello.prg ] || fail "hello.prg missing or empty"

# ca65/ld65 round-trip (spec §10).
"$BIN/ca65" "$FIXTURES/hello.s" -o hello.o || fail "ca65 hello.s failed"
"$BIN/ld65" -o hello2.prg hello.o || fail "ld65 round-trip failed"
[ -s hello2.prg ] || fail "hello2.prg missing or empty"

echo "test.sh(cc65): OK"
