#!/usr/bin/env bash
# build.sh — tass64/64tass (spec §10)
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
make -j"$NPROC" CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
# mkdir -p, not install -D: BSD/macOS install has no -D (create-dirs), so
# this would die with a temp-file ENOENT on the macOS runner (first CI leg).
mkdir -p "$PREFIX/bin"
install -m755 64tass "$PREFIX/bin/64tass"
install -m644 README "$PREFIX/"
