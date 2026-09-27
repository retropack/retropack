#!/usr/bin/env bash
# test.sh — smoke-test oscar64 in $PREFIX (spec §6.3, §10)
set -euo pipefail

: "${PREFIX:?PREFIX must be set}"
BIN="$PREFIX/bin"
FIXTURES="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

fail() { echo "test.sh(oscar64): $*" >&2; exit 1; }

[ -x "$BIN/oscar64" ] || fail "missing or not executable: $BIN/oscar64"
# -v is oscar64's version flag ("Starting oscar64 <version>", exit 0);
# there is no --help (it errors with exit 20).
"$BIN/oscar64" -v >/dev/null || fail "oscar64 -v failed"

# Copy the fixture first: oscar64 writes ALL outputs (.prg/.int/.lbl/.map)
# next to the SOURCE file, so compiling the fixture in place would pollute
# fixtures/ and leave the temp dir empty.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
cp "$FIXTURES/hello.c" .
"$BIN/oscar64" hello.c || fail "oscar64 hello.c failed"
PRG="$(find . -name '*.prg' | head -n1)"
if [ -z "$PRG" ] || [ ! -s "$PRG" ]; then
  fail "no non-empty .prg produced"
fi

echo "test.sh(oscar64): OK"
