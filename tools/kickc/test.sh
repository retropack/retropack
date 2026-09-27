#!/usr/bin/env bash
# test.sh — smoke-test kickc (noarch/JVM) in $PREFIX (spec §6.3, §10)
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(kickc): $*" >&2; exit 1; }

command -v java >/dev/null || fail "java not on PATH (runtime requirement: java>=11)"
[ -x "$BIN/kickc" ] || fail "missing or not executable: $BIN/kickc"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
"$BIN/kickc" -t c64 "$FIXTURES/hello.c" || fail "kickc hello.c failed"
PRG="$(find . \( -name '*.prg' -o -name '*.bin' \) | head -n1)"
if [ -z "$PRG" ] || [ ! -s "$PRG" ]; then
  fail "no non-empty output produced"
fi

echo "test.sh(kickc): OK"
