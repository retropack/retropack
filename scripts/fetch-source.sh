#!/usr/bin/env bash
# fetch-source.sh — download + verify + extract source per tools/<tool>/tool.toml (spec §5, §6.1)
# Steps: read tool.toml → resolve source URL (watch.py) → download → pin check →
# extract with strip_components → apply tools/<tool>/patches/* in order (-p1).
set -euo pipefail

: "${TOOL:?TOOL must be set}"
: "${VERSION:?VERSION must be set}"
: "${WORK:?WORK must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/tools/$TOOL/tool.toml"
[ -f "$MANIFEST" ] || { echo "fetch-source: no manifest $MANIFEST" >&2; exit 1; }

# Read manifest facts.
read -r STRIP <<EOF
$(python3 - "$MANIFEST" <<'PY'
import tomllib, sys
t = tomllib.load(open(sys.argv[1], "rb"))
print(t["source"].get("strip_components", 1))
PY
)
EOF

# SRC_URL env override exists for tests (tests/test_fetch_source.py).
# URL resolution (template, or the GitLab release-asset lookup for repackage
# mode) lives in watch.py so the watcher's pin PRs hash exactly the bytes the
# build will download — two resolvers could drift, one cannot.
if [ -z "${SRC_URL:-}" ]; then
  SRC_URL=$(python3 "$REPO_ROOT/scripts/watch.py" --source-url "$TOOL" "$VERSION")
fi

SRC="${SRC:-$WORK/src}"
mkdir -p "$WORK" "$SRC"
ARCHIVE="$WORK/src-archive"

# HTTPS-only for the initial request and every redirect (spec §5's integrity
# stance hardened against protocol-downgrade redirects); file:// stays
# allowed for the local tests. Capture the EFFECTIVE (post-redirect) URL —
# package.sh cites it in the RETROPACK-NOTICE so provenance names the exact
# file shipped (matters for repackage: shortener → stable wiki upload URL).
# HTTPS only; file:// is admitted solely alongside the test-only SRC_URL
# override (security review F4) — a hostile manifest URL or repackage
# release-asset link can never aim curl at local files.
PROTO='=https'
if [ -n "${SRC_URL:-}" ]; then
  PROTO='=https,file'
fi
EFFECTIVE=$(curl -fsSL --proto "$PROTO" --proto-redir '=https' \
  -w '%{url_effective}' -o "$ARCHIVE" "$SRC_URL")
printf '%s\n' "$EFFECTIVE" > "$WORK/.source-url"

# Reviewed-hash gate (spec §8.1): once tools/<tool>/source-sha256.txt exists,
# $VERSION must have a pin matching the downloaded bytes — the watcher only
# dispatches pinned versions, so a miss here means a forced/manual build of
# unreviewed source. Until the file exists the tool is ungated (the first
# pins-PR merge flips it, permanently).
PINS="$REPO_ROOT/tools/$TOOL/source-sha256.txt"
if [ -f "$PINS" ]; then
  PIN=$(awk -v v="$VERSION" '$1 !~ /^#/ && $2 == v {print $1; exit}' "$PINS")
  if [ -z "$PIN" ]; then
    echo "fetch-source: no pin for $TOOL $VERSION in tools/$TOOL/source-sha256.txt" >&2
    echo "  → python3 scripts/watch.py --source-sha256 $TOOL $VERSION, review, PR the pin" >&2
    exit 1
  fi
  if ! python3 - "$ARCHIVE" "$PIN" <<'PY'
import hashlib, sys
h = hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest()
sys.exit(0 if h == sys.argv[2] else 1)
PY
  then
    echo "fetch-source: sha256 mismatch for $TOOL $VERSION — upstream bits changed after review?" >&2
    exit 1
  fi
fi

# Detect format by magic bytes, not URL suffix: SourceForge download URLs end
# in `/download`, not `.zip` (spec §10 tass64).
MAGIC="$(head -c 2 "$ARCHIVE" | od -An -tx1 | tr -d ' \n')"
case "$MAGIC" in
  504b*)                              # PK…
    unzip -q -o "$ARCHIVE" -d "$SRC"
    # unzip has no --strip-components: strip one level by moving the single
    # top-level dir's contents up. (Ceiling: zips support strip 0/1 only —
    # no current tool needs more.)
    if [ "$STRIP" -ge 1 ]; then
      [ "$STRIP" -le 1 ] || { echo "fetch-source: zip strip_components > 1 unsupported" >&2; exit 1; }
      top=$(find "$SRC" -mindepth 1 -maxdepth 1)
      n=$(printf '%s\n' "$top" | grep -c .)
      if [ "$n" -ne 1 ] || [ ! -d "$top" ]; then
        echo "fetch-source: expected a single top-level dir in zip to strip, found: $top" >&2
        exit 1
      fi
      cp -a "$top"/. "$SRC"/ && rm -rf "$top"
    fi
    ;;
  1f8b*)                              # gzip
    # --no-same-owner (security review F5): builds run as root in the linux
    # container; archive-provided ownership must never be restored.
    # (bsdtar on the macOS leg accepts the flag too.)
    tar --no-same-owner -xzf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
  425a*)                              # BZh — sdcc ships .tar.bz2 exclusively
    tar --no-same-owner -xjf "$ARCHIVE" -C "$SRC" --strip-components="$STRIP"
    ;;
  *)
    echo "fetch-source: unrecognized archive format for $SRC_URL (magic $MAGIC)" >&2
    exit 1
    ;;
esac

if [ -d "$REPO_ROOT/tools/$TOOL/patches" ]; then
  for p in "$REPO_ROOT/tools/$TOOL/patches"/*; do
    [ -e "$p" ] || continue
    if [ -d "$p" ]; then
      # Version-scoped: patches/<version>/ applies ONLY to that exact version
      # (e.g. tass64's memalign rename exists in 1.59.3120 and nowhere else).
      [ "$(basename "$p")" = "$VERSION" ] || continue
      for q in "$p"/*; do
        [ -f "$q" ] || continue
        patch -d "$SRC" -p1 < "$q"
      done
    else
      patch -d "$SRC" -p1 < "$p"
    fi
  done
fi

echo "fetch-source: SRC=$SRC"
