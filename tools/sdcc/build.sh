#!/usr/bin/env bash
# build.sh — sdcc (spec §10): 6502/Z80 ports only, non-free libs excluded.
# Heaviest build: timeout_minutes = 90 in tool.toml.
set -euo pipefail

: "${SRC:?SRC must be set}"
: "${PREFIX:?PREFIX must be set}"
: "${NPROC:?NPROC must be set}"

cd "$SRC"
# --without-zstd: the bundled sdbinutils/bfd auto-detects zstd (pkg-config
# finds Homebrew's on macOS) and links its dylib — §6.4 forbids non-system
# dylibs on macOS, and sdcc has no use for compressed debug sections. The
# flag is forwarded down the AC_CONFIG_SUBDIRS chain to bfd/configure
# (verified present in 4.6.0's configure).
./configure --prefix="$PREFIX" \
  --disable-pic14-port --disable-pic16-port \
  --disable-non-free --disable-ucsim --disable-doc \
  --without-zstd
# sdcc's vendored sdbinutils links through libtool, which swallows plain
# -static: its c++filt/sdar/sdnm/sdobjcopy/sdranlib came out dynamically
# linked against musl (unusable on glibc hosts; check-portability failure).
# libtool's -all-static forwards -static to gcc (verified: static-pie).
# AM_LDFLAGS (not LDFLAGS): it reaches the automake/libtool link lines but
# never configure's conftests — gcc rejects the unknown -all-static there,
# and an LDFLAGS override broke the nested configure steps. Scoped to this
# one target; the override reaches the sub-make via MAKEFLAGS.
make -j"$NPROC" sdcc-sdbinutils AM_LDFLAGS="-all-static"
make -j"$NPROC"
make install
# libtool .la metadata embeds absolute build paths (spec §6.4 forbids them) and
# is only needed to relink against those internal binutils libs with libtool —
# which sdcc users never do. Dropping them is standard distro practice.
rm -f "$PREFIX"/lib/*.la
# Relocatability (bin/../share/sdcc) is proven by test.sh from an arbitrary path.
