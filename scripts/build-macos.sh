#!/usr/bin/env bash
# build-macos.sh — host-side wrapper for macOS runners (spec §6.2)
# Presets: CC=clang CXX=clang++ MACOSX_DEPLOYMENT_TARGET=12.0 CFLAGS="-O2".
set -euo pipefail

: "${TOOL:?TOOL must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NPROC="${NPROC:-$(sysctl -n hw.ncpu)}"

# Build-time Homebrew packages (tool.toml macos_packages) are installed by the
# caller; binaries must not link any /opt/homebrew dylib (check-portability.sh).
export CC=clang CXX=clang++
export MACOSX_DEPLOYMENT_TARGET=12.0
export CFLAGS="-O2"
export NPROC

sh "$REPO_ROOT/tools/$TOOL/build.sh"
