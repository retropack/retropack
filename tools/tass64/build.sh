#!/usr/bin/env bash
# build.sh — tass64/64tass (spec §10)
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
make -j"$NPROC" CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
install -Dm755 64tass "$PREFIX/bin/64tass"
install -Dm644 README "$PREFIX/"
