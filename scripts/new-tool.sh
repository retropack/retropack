#!/usr/bin/env bash
# new-tool.sh — scaffold tool repo + tools/<tool>/ (spec §11)
# Usage: scripts/new-tool.sh <tool>
# Creates tools/<tool>/ from tools/_template/, then prints the gh commands to
# run manually (no network side effects from this script).
set -euo pipefail

: "${1:?usage: new-tool.sh <tool>}"
TOOL="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[[ "$TOOL" =~ ^[a-z0-9-]+$ ]] || { echo "new-tool: name must match ^[a-z0-9-]+$" >&2; exit 1; }
[ ! -e "$REPO_ROOT/tools/$TOOL" ] || { echo "new-tool: tools/$TOOL already exists" >&2; exit 1; }

mkdir -p "$REPO_ROOT/tools/$TOOL/fixtures"
sed "s/^name *=.*/name         = \"$TOOL\"/" "$REPO_ROOT/tools/_template/tool.toml" \
  > "$REPO_ROOT/tools/$TOOL/tool.toml"
cp "$REPO_ROOT/tools/_template/build.sh" "$REPO_ROOT/tools/$TOOL/build.sh"
cp "$REPO_ROOT/tools/_template/test.sh" "$REPO_ROOT/tools/$TOOL/test.sh"
chmod +x "$REPO_ROOT/tools/$TOOL/build.sh" "$REPO_ROOT/tools/$TOOL/test.sh"

echo "new-tool: scaffolded tools/$TOOL/ (fill in tool.toml, build.sh, test.sh, fixtures/)"
echo
echo "Next steps (manual):"
echo "  1. Create the release repo and push the template:"
echo "       gh repo create retropack/$TOOL --public --description '...'"
echo "       git -C <clone-of-retropack/$TOOL> add templates/tool-repo/. && git commit -m 'stub' && git push"
echo "     (or: gh repo create retropack/$TOOL --template retropack/tool-template)"
echo "  2. Open a PR in retropack/retropack with tools/$TOOL/ (ci.yml validates it)."
echo "  3. After merge: gh workflow run watch.yml -f tool=$TOOL"
