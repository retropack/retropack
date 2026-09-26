#!/usr/bin/env bash
# build.sh — oscar64 (spec §10)
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
# TODO: expect Makefile patches (hard-coded flags); keep them in patches/
make -C make -j"$NPROC" CXX="$CXX"
install -Dm755 bin/oscar64 "$PREFIX/bin/oscar64"
cp -r include "$PREFIX/include"
