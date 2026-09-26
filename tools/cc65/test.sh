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

# Work on copies in a temp dir: cl65 writes its intermediate .s/.o next to the
# source file (named hello.s for hello.c — which is why the asm fixture is
# asm_hello.s: cl65 would overwrite and unlink it otherwise; strace-verified).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
mkdir asm && cp "$FIXTURES/hello.c" . && cp "$FIXTURES/asm_hello.s" "$FIXTURES/flat.cfg" asm/

# End-to-end C compile for C64 (spec §6.3).
cl65_bin="$BIN/cl65"
"$cl65_bin" -t c64 hello.c -o hello.prg || fail "cl65 hello.c failed"
[ -s hello.prg ] || fail "hello.prg missing or empty"

# ca65/ld65 round-trip (spec §10) with a minimal linker config: ld65 requires
# -C, and c64.cfg needs crt0 symbols a bare object doesn't define.
"$BIN/ca65" asm/asm_hello.s -o asm/hello.o || fail "ca65 asm_hello.s failed"
"$BIN/ld65" -C asm/flat.cfg -o hello2.prg asm/hello.o || fail "ld65 round-trip failed"
[ -s hello2.prg ] || fail "hello2.prg missing or empty"

echo "test.sh(cc65): OK"
