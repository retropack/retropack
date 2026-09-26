#!/usr/bin/env bash
# build.sh — sdcc (spec §10): 6502/Z80 ports only, non-free libs excluded.
# Heaviest build: timeout_minutes = 90 in tool.toml.
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
./configure --prefix="$PREFIX" \
  --disable-pic14-port --disable-pic16-port \
  --disable-non-free --disable-ucsim --disable-doc
make -j"$NPROC"
make install
# Relocatability (bin/../share/sdcc) is proven by test.sh from an arbitrary path.
