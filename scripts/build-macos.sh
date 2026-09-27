#!/usr/bin/env bash
# build-macos.sh — host-side wrapper for macOS runners (spec §6.2)
# Presets: CC=clang CXX=clang++ MACOSX_DEPLOYMENT_TARGET=12.0 CFLAGS="-O2".
set -euo pipefail

: "${TOOL:?TOOL must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NPROC="${NPROC:-$(sysctl -n hw.ncpu)}"

# Build-time Homebrew packages (tool.toml macos_packages) are installed by the
# caller; binaries must not link any /opt/homebrew dylib (check-portability.sh).
# Keg-only formulae (bison, flex — Homebrew does NOT symlink them) must shadow
# Apple's ancient copies: prepend their opt/ bin dirs to PATH (spec §10: "force
# PATH to Homebrew bison"). Applies to every macos_packages entry — a missing
# dir (e.g. boost, header-only) is simply skipped.
if command -v brew >/dev/null 2>&1; then
  BREW_PREFIX=$(brew --prefix)
  _pkgs=$(python3 -c "
import tomllib
print(' '.join(tomllib.load(open('$REPO_ROOT/tools/$TOOL/tool.toml', 'rb'))['build'].get('macos_packages', [])))")
  for _p in $_pkgs; do
    if [ -d "$BREW_PREFIX/opt/$_p/bin" ]; then
      PATH="$BREW_PREFIX/opt/$_p/bin:$PATH"
    fi
  done
  export PATH
  # Apple clang does not search Homebrew's prefix by default — sdcc's
  # configure dies on boost/graph/adjacency_list.hpp without this (headers
  # live in $BREW_PREFIX/include; boost is header-only so the -L never puts a
  # Homebrew dylib in the binary — check-portability enforces that).
  export CPPFLAGS="${CPPFLAGS:+$CPPFLAGS }-I$BREW_PREFIX/include"
  export LDFLAGS="${LDFLAGS:+$LDFLAGS }-L$BREW_PREFIX/lib"
fi
export CC=clang CXX=clang++
export MACOSX_DEPLOYMENT_TARGET=12.0
export CFLAGS="-O2"
# §6.1 env contract: build.sh reads $LDFLAGS under set -u — macOS has no
# static-link preset (spec §6.2), so default it to empty but always defined.
export LDFLAGS="${LDFLAGS:-}"
export NPROC

sh "$REPO_ROOT/tools/$TOOL/build.sh"
