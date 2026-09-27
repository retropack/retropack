#!/usr/bin/env bash
# local-build.sh — run the full retropack pipeline for one tool on THIS machine.
#
# usage: scripts/local-build.sh <tool> [version]      version defaults to latest upstream
# e.g.:  scripts/local-build.sh cc65
#        scripts/local-build.sh cc65 2.19
#
# Runs the same steps as CI's build job (fetch → build → test → portability →
# package) for the local platform (spec §2.2): linux builds go through the
# alpine docker wrapper, macOS runs natively, platform-independent tools build
# directly on the host (spec §6.2 noarch).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
  local tools="" t
  for t in tools/*/; do
    t=${t#tools/}
    t=${t%/}
    if [ "$t" != "_template" ]; then tools="$tools$t "; fi
  done
  echo "usage: $0 <tool> [version]   (tools: $tools; version defaults to latest upstream)" >&2
  exit 2
}

TOOL="${1:-}"
[ -n "$TOOL" ] || usage
[ -f "tools/$TOOL/tool.toml" ] || { echo "local-build: unknown tool '$TOOL'" >&2; usage; }

# Local platform (spec §2.2); anything else is out of scope (spec §1.2).
case "$(uname -s)/$(uname -m)" in
  Linux/x86_64)                OS=linux; ARCH=x86_64 ;;
  Linux/aarch64|Linux/arm64)   OS=linux; ARCH=aarch64 ;;
  Darwin/arm64)                OS=macos; ARCH=aarch64 ;;
  *) echo "local-build: unsupported platform $(uname -s)/$(uname -m) (spec §2.2)" >&2; exit 1 ;;
esac
PLATFORM="$OS-$ARCH"

# platform_independent tools build once on this host (spec §6.2 noarch).
if python3 -c "import tomllib,sys; sys.exit(0 if tomllib.load(open('tools/$TOOL/tool.toml','rb'))['tool']['platform_independent'] else 1)"; then
  PLATFORM=noarch
fi

VERSION="${2:-}"
if [ -z "$VERSION" ]; then
  # watch.py prints one line to stdout and exits non-zero when nothing matches.
  VERSION="$(python3 scripts/watch.py --latest-for "$TOOL")" || exit 1
fi

export TOOL VERSION PLATFORM OS ARCH
export WORK="$REPO_ROOT/work" SRC="$REPO_ROOT/work/src"
export PREFIX="$REPO_ROOT/work/$TOOL-$VERSION"
export NPROC="${NPROC:-$(nproc 2>/dev/null || sysctl -n hw.ncpu)}"

# Platform build presets (spec §6.2); build-macos.sh sets its own clang presets.
case "$PLATFORM" in
  linux-*) export CC=gcc CXX=g++ CFLAGS=-O2 LDFLAGS=-static ;;
  noarch)  export CFLAGS="${CFLAGS:--O2}" LDFLAGS="${LDFLAGS:-}" ;;
esac

# macOS build-time deps are the caller's job (spec §6.2) — remind, don't brew.
if [ "$OS" = macos ]; then
  pkgs=$(python3 -c "import tomllib; print(' '.join(tomllib.load(open('tools/$TOOL/tool.toml','rb'))['build'].get('macos_packages',[])))")
  if [ -n "$pkgs" ]; then
    echo "local-build: make sure build deps are installed: brew install $pkgs"
  fi
fi

echo "==> local-build: $TOOL $VERSION ($PLATFORM)"
rm -rf "$WORK"    # fresh every run — what you test is what you'd ship

echo "==> fetch"
scripts/fetch-source.sh

echo "==> build"
case "$PLATFORM" in
  linux-*) scripts/build-linux.sh ;;
  macos-*) scripts/build-macos.sh ;;
  noarch)  sh "tools/$TOOL/build.sh" ;;
esac

echo "==> test"
PREFIX="$PREFIX" "tools/$TOOL/test.sh"

echo "==> portability"
PLATFORM="$PLATFORM" PREFIX="$PREFIX" scripts/check-portability.sh

echo "==> package"
scripts/package.sh

echo "==> done: dist/$TOOL-$VERSION-$PLATFORM.tar.gz"
