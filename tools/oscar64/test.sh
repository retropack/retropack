#!/usr/bin/env bash
# test.sh — smoke-test oscar64 in $PREFIX (spec §6.3, §10)
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(oscar64): $*" >&2; exit 1; }

[ -x "$BIN/oscar64" ] || fail "missing or not executable: $BIN/oscar64"
"$BIN/oscar64" --help >/dev/null 2>&1 || fail "oscar64 invocation failed"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
"$BIN/oscar64" "$FIXTURES/hello.c" || fail "oscar64 hello.c failed"
PRG="$(find . -name '*.prg' | head -n1)"
[ -n "$PRG" ] && [ -s "$PRG" ] || fail "no non-empty .prg produced"

echo "test.sh(oscar64): OK"
