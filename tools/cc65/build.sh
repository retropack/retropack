#!/usr/bin/env bash
# build.sh — cc65 (spec §10): make, install into $PREFIX with relocatable data dirs.
# Env contract (spec §6.1): TOOL VERSION PLATFORM SRC PREFIX NPROC CC CXX CFLAGS LDFLAGS
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
make -j"$NPROC" CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS" \
  || { echo "build.sh(cc65): make failed" >&2; exit 1; }
# cc65's Makefile uses PREFIX; binaries search ../lib etc. relative to bin/ first.
make install PREFIX="$PREFIX" prefix="$PREFIX"
# doc build intentionally skipped (spec §10).
