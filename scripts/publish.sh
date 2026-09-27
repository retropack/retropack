#!/usr/bin/env bash
# publish.sh — release publishing for the retropack pipeline (spec §7.4).
#
# usage: scripts/publish.sh <assets|upload|release>
#   assets  — noarch fan-out to the three platform names + aggregate
#             SHA256SUMS (spec §7.1; per-asset .sha256 dropped after §13
#             showed mise verifies via GitHub's API asset digest).
#   upload  — spec §7.4 steps 1–4: published-release short-circuit, delete
#             stale draft, create draft targeting main, upload all assets.
#   release — spec §7.4 step 6: draft → published, --latest only when this
#             is the highest published version (backfills must not steal it).
#
# upload/release require: GH_TOKEN, GITHUB_REPOSITORY (set by Actions),
# TOOL, VERSION.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="${DIST:-$REPO_ROOT/dist}"
phase="${1:-}"

# VERSION feeds API paths, release ids and the --latest decision — accept only
# normalized numeric-dotted versions (spec §5) before anything consumes it
# (security review: crafted versions steered jq/release lookups).
validate_version() {
  if ! printf '%s\n' "$VERSION" | grep -Eq '^[0-9]+(\.[0-9]+)*$'; then
    echo "publish: invalid version '$VERSION'" >&2
    exit 1
  fi
}

assets() {
  # noarch fan-out: the same bytes published under all three platform names
  # so mise autodetection always finds a match (spec §7.1 — the -noarch name
  # itself is never used).
  if [ "${PLATFORM_INDEPENDENT:-false}" = "true" ]; then
    for f in "$DIST"/*-noarch.tar.gz; do
      [ -e "$f" ] || continue
      local base="${f%-noarch.tar.gz}"
      local p
      for p in linux-x86_64 linux-aarch64 macos-aarch64; do
        cp -f "$f" "$base-$p.tar.gz"
      done
      rm -f "$f"
    done
  fi

  shopt -s nullglob
  local archives=("$DIST"/*.tar.gz)
  shopt -u nullglob
  if [ "${#archives[@]}" -eq 0 ]; then
    echo "publish: no archives in $DIST" >&2
    exit 1
  fi

  # One aggregate SHA256SUMS for humans (§13 resolved: mise verifies via
  # GitHub's API asset digest — it never reads per-asset .sha256 files, so
  # those are no longer published). The rm clears stale ones from old runs.
  rm -f "$DIST"/SHA256SUMS "$DIST"/*.sha256
  (
    cd "$DIST"
    sha256sum -- *.tar.gz > SHA256SUMS
  )
  echo "publish: assets prepared in $DIST"
}

draft_id_for() {
  # Drafts have no tag ref yet, so query the releases LIST (spec §7.4 step 2).
  # Constant jq program; the tag is passed to awk as data, never interpolated
  # into the program text (security review: jq injection → wrong release id).
  gh api "repos/$1/releases?per_page=100" \
    --jq '.[] | "\(.id)\t\(.tag_name)\t\(.draft)"' \
    | awk -F'\t' -v t="$2" '$2 == t && $3 == "true" { print $1; exit }'
}

upload() {
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
  : "${VERSION:?VERSION must be set}"
  validate_version
  local repo="$GITHUB_REPOSITORY" tag="v$VERSION"

  # 1. Already published → nothing to do (idempotent).
  if gh release view "$tag" --repo "$repo" > /dev/null 2>&1; then
    echo "publish: $tag already released"
    return 0
  fi

  # 2. Stale draft from a failed run → delete it.
  local draft_id
  draft_id=$(draft_id_for "$repo" "$tag")
  if [ -n "$draft_id" ]; then
    gh api -X DELETE "repos/$repo/releases/drafts/$draft_id" > /dev/null
  fi

  # 3. Draft release targeting main; body = install snippet + checksums.
  local notes
  notes=$(
    echo "Prebuilt by [retropack](https://github.com/retropack/retropack) from upstream sources."
    echo
    echo '```sh'
    echo "mise install github:$repo@$VERSION"
    echo '```'
    echo
    echo "### SHA256SUMS"
    echo '```'
    cat "$DIST/SHA256SUMS"
    echo '```'
  )
  gh release create "$tag" --repo "$repo" --draft --target main \
    --title "$tag" --notes "$notes"

  # 4. Upload every asset: the archives and the aggregate SHA256SUMS.
  gh release upload "$tag" --repo "$repo" --clobber \
    "$DIST"/*.tar.gz "$DIST"/SHA256SUMS
  echo "publish: $tag draft uploaded"
}

release() {
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
  : "${VERSION:?VERSION must be set}"
  validate_version
  local repo="$GITHUB_REPOSITORY" tag="v$VERSION"

  local draft_id
  draft_id=$(draft_id_for "$repo" "$tag")
  if [ -z "$draft_id" ]; then
    if gh release view "$tag" --repo "$repo" > /dev/null 2>&1; then
      echo "publish: $tag already published"
      return 0
    fi
    echo "publish: no draft $tag to publish" >&2
    return 1
  fi

  # --latest only when this is the highest published version — backfilling
  # older versions must not steal "latest" (spec §7.4 step 6). Comparison
  # reuses watch.py's lenient version compare (single source of truth).
  local latest
  latest=$(gh api "repos/$repo/releases?per_page=100" |
    python3 "$REPO_ROOT/scripts/watch.py" --latest-flag "$VERSION")
  gh api -X PATCH "repos/$repo/releases/$draft_id" \
    -F draft=false -F "latest=$latest" > /dev/null
  echo "publish: $tag published (latest=$latest)"
}

case "$phase" in
  assets)  assets ;;
  upload)  upload ;;
  release) release ;;
  *) echo "usage: $0 <assets|upload|release>" >&2; exit 2 ;;
esac
