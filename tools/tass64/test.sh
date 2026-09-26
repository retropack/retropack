#!/usr/bin/env bash
# test.sh — smoke-test tass64/64tass in $PREFIX (spec §6.3, §10)
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(tass64): $*" >&2; exit 1; }

[ -x "$BIN/64tass" ] || fail "missing or not executable: $BIN/64tass"
"$BIN/64tass" --version >/dev/null 2>&1 || "$BIN/64tass" -V >/dev/null 2>&1 \
  || fail "64tass version check failed"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
"$BIN/64tass" "$FIXTURES/hello.asm" -o hello.prg || fail "64tass hello.asm failed"
[ -s hello.prg ] || fail "hello.prg missing or empty"

echo "test.sh(tass64): OK"
