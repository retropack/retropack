#!/usr/bin/env bash
# check-portability.sh — static-ness / dylib checks on a built prefix (spec §6.4)
# Env contract: PLATFORM, PREFIX (and /work/ path rule applies to the staging dir).
set -euo pipefail

: "${PLATFORM:?PLATFORM must be set}"
: "${PREFIX:?PREFIX must be set}"
[ -d "$PREFIX" ] || { echo "check-portability: PREFIX $PREFIX does not exist" >&2; exit 1; }

fail() { echo "check-portability: $*" >&2; exit 1; }

case "$PLATFORM" in
  linux-*)
    for f in "$PREFIX"/bin/*; do
      [ -f "$f" ] || continue
      # Skip non-ELF entries (JVM wrapper scripts).
      file -b "$f" | grep -q "^ELF" || continue
      file -b "$f" | grep -q "statically linked" || fail "$f is not statically linked: $(file -b "$f")"
      if readelf -d "$f" 2>/dev/null | grep -q NEEDED; then
        fail "$f has dynamic NEEDED entries"
      fi
    done
    ;;
  macos-*)
    for f in "$PREFIX"/bin/*; do
      [ -f "$f" ] || continue
      file -b "$f" | grep -q "Mach-O" || continue
      # Only /usr/lib and /System dylibs allowed.
      otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -Ev '^(/usr/lib/|/System/)' \
        && fail "$f links non-system dylibs"
      codesign --verify --strict "$f" || fail "$f fails codesign --verify"
      otool -l "$f" | grep -q minos || fail "$f has no minos (deployment target) load command"
    done
    ;;
  noarch)
    # wrapper scripts only; nothing binary to check
    ;;
  *)
    fail "unknown PLATFORM $PLATFORM"
    ;;
esac

# All platforms: no absolute build paths in text files under the prefix.
if grep -rIl "/work/" "$PREFIX" >/dev/null 2>&1; then
  grep -rIl "/work/" "$PREFIX" >&2 || true
  fail "absolute build paths (/work/) found in prefix"
fi

echo "check-portability: OK ($PLATFORM)"
