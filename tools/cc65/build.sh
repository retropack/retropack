#!/usr/bin/env bash
# build.sh — cc65 (spec §10): make, install into $PREFIX with relocatable data dirs.
# Env contract (spec §6.1): TOOL VERSION PLATFORM SRC PREFIX NPROC CC CXX CFLAGS LDFLAGS
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
# Order matters:
# 1. src/ first — libsrc's Makefile picks ../bin/cc65 only if it exists
#    (line 259; otherwise it falls back to `cc65` on PATH, which alpine lacks).
# 2. apple2enh prebuild guards a cc65 V2.19 -j race: targetutil/Makefile.inc
#    nests `$(MAKE) apple2enh` for ../lib/apple2enh.lib while the TARGETS loop
#    builds apple2enh concurrently — ar65's fixed .temp filename then gets
#    double-unlinked (ENOENT) and the library can be corrupted. With the lib
#    prebuilt, the nested rule is a no-op (file exists, no prereqs).
# 3. USER_CFLAGS, not CFLAGS: cc65's Makefile appends `-I common` etc. to its
#    own CFLAGS — CFLAGS= on the command line would wipe it (spec §6.1: append,
#    not replace).
# doc/ is never built (spec §10).
make -C src -j"$NPROC" USER_CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
make -C libsrc apple2enh -j"$NPROC" USER_CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
make -C libsrc -j"$NPROC" USER_CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS" \
  || { echo "build.sh(cc65): make failed" >&2; exit 1; }
# Install bin/ plus the support trees libsrc owns — lib, include, asminc, cfg,
# target (spec §2.1); binaries search ../lib etc. relative to bin/ first.
make -C src install PREFIX="$PREFIX" prefix="$PREFIX"
make -C libsrc install PREFIX="$PREFIX" prefix="$PREFIX"
# libsrc installs to $PREFIX/share/cc65/... — flatten it beside bin/ so the
# binaries' ../lib-relative lookup works and the prefix stays relocatable
# (spec §10: "flatten to $PREFIX/{lib,include,asminc,cfg,target}").
for d in lib asminc cfg include target; do
  if [ -d "$PREFIX/share/cc65/$d" ]; then
    mv "$PREFIX/share/cc65/$d" "$PREFIX/$d"
  fi
done
rm -rf "$PREFIX/share"
# cc65 V2.19 bakes ABSOLUTE data-dir paths at compile time and has no
# exe-relative lookup (verified; this is spec §13's relocatability open item),
# and the compile-time path points into the build container — useless after
# mise moves the tree. Wrap every binary so CC65_HOME points at the prefix at
# runtime (same wrapper mechanism spec §7.2 prescribes for JVM tools).
# Real binaries stay beside the wrappers as *.real.
# Real binaries go to libexec/ beside bin/ — the wrapper's argv[0] then
# basename()s to the clean tool name (`cl65`, not `cl65.real`) in --version.
for b in cc65 ca65 cl65 ld65 ar65 co65 da65 od65 sp65 grc65 sim65; do
  [ -f "$PREFIX/bin/$b" ] || continue
  mkdir -p "$PREFIX/libexec"
  mv "$PREFIX/bin/$b" "$PREFIX/libexec/$b"
  # shellcheck disable=SC2016  # single quotes are deliberate: the generated
  # wrapper must expand $0/$d at runtime, not here
  printf '%s\n' \
    '#!/bin/sh' \
    '# Relocatable launcher: cc65 V2.19 bakes absolute data-dir paths at' \
    '# compile time (no exe-relative lookup); CC65_HOME relocates them.' \
    'd=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)' \
    'export CC65_HOME="${CC65_HOME:-$(dirname "$d")}"' \
    "exec \"\$d/../libexec/$b\" \"\$@\"" > "$PREFIX/bin/$b"
  chmod +x "$PREFIX/bin/$b"
done
