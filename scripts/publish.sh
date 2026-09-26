#!/usr/bin/env bash
# publish.sh — idempotent draft→assets→undraft release (spec §7.4). Tool-repo GITHUB_TOKEN.
#
# TODO(M1) — steps (spec §7.4, in order):
#   1. If published (non-draft) release v<VERSION> exists → exit 0 ("already released").
#   2. If draft release v<VERSION> exists → delete it (leftover of a failed run).
#   3. Create release v<VERSION> as draft targeting main, body from template
#      (upstream link, install snippet, checksums); generated notes disabled.
#   4. Upload all assets + SHA256SUMS + per-asset .sha256 files.
#   5. Run actions/attest-build-provenance on all archives (subject-path: dist/*.tar.gz).
#   6. Flip draft → published; pass --latest only if <VERSION> is the highest
#      published version (backfills must not steal "latest").
set -euo pipefail

: "${TOOL:?TOOL must be set}"
: "${VERSION:?VERSION must be set}"

echo "publish: not implemented yet (M1)" >&2
exit 1
