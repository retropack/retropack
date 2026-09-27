#!/usr/bin/env bash
# build.sh — oscar64 (spec §10)
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
# TODO: expect Makefile patches (hard-coded flags); keep them in patches/
make -C make -j"$NPROC" CXX="$CXX"
# mkdir -p, not install -D: BSD/macOS install has no -D (create-dirs) — this
# pattern broke tass64's macOS leg before it was caught here.
mkdir -p "$PREFIX/bin"
install -m755 bin/oscar64 "$PREFIX/bin/oscar64"
cp -r include "$PREFIX/include"
