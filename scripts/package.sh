#!/usr/bin/env bash
# package.sh — produce dist/<tool>-<version>-<platform>.tar.gz + RETROPACK-NOTICE (spec §7.1–7.3)
# Env contract (spec §6.1): TOOL VERSION PLATFORM SRC PREFIX
# The archive holds exactly one top-level dir <tool>-<version>/ (mise strips it).
set -euo pipefail

: "${TOOL:?TOOL must be set}"
: "${VERSION:?VERSION must be set}"
: "${PLATFORM:?PLATFORM must be set}"
: "${PREFIX:?PREFIX must be set}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$REPO_ROOT/tools/$TOOL/tool.toml"
DIST="$REPO_ROOT/dist"
mkdir -p "$DIST"

# PREFIX is already <work>/<tool>-<version>/; tar runs from its parent below.
[ -d "$PREFIX" ] || { echo "package: PREFIX $PREFIX does not exist" >&2; exit 1; }

# Copy upstream licence files (paths relative to source tree) into the prefix.
if [ -n "${SRC:-}" ]; then
  while IFS= read -r lic; do
    cp "$SRC/$lic" "$PREFIX/" 2>/dev/null || echo "package: warning: licence file $lic not found in SRC" >&2
  done < <(python3 - "$MANIFEST" <<'PY'
import tomllib, sys
t = tomllib.loads(open(sys.argv[1], "rb").read())
for f in t["tool"].get("license_files", []):
    print(f)
PY
)
fi

# Generate RETROPACK-NOTICE from the template (spec §7.3).
python3 - "$MANIFEST" "$VERSION" "$PLATFORM" "$REPO_ROOT/templates/RETROPACK-NOTICE.tmpl" "$PREFIX/RETROPACK-NOTICE" <<'PY'
import os, sys, tomllib, datetime
manifest, version, platform, tmpl_path, out_path = sys.argv[1:6]
t = tomllib.loads(open(manifest, "rb").read())
tool = t["tool"]
up = t["upstream"]
notice = open(tmpl_path).read()
for field, value in {
    "tool": tool["name"],
    "version": version,
    "homepage": tool.get("homepage", ""),
    "source_url": t["source"]["url"].replace("{version}", version),
    "source_tag": f"v{version}",
    "license": tool.get("license", ""),
    "patches": ", ".join(sorted(os.listdir(os.path.join(os.path.dirname(manifest), "patches"))))
        if os.path.isdir(os.path.join(os.path.dirname(manifest), "patches")) else "none",
    "platform": platform,
    "build_date": datetime.date.today().isoformat(),
    "run_url": os.environ.get("GITHUB_SERVER_URL", "") + "/" + os.environ.get("GITHUB_REPOSITORY", "")
        + "/actions/runs/" + os.environ.get("GITHUB_RUN_ID", ""),
    "runtime_requirements": ", ".join(tool.get("runtime_requirements", [])) or "none",
}.items():
    notice = notice.replace("{{%s}}" % field, value)
open(out_path, "w").write(notice)
PY

# tar from the parent so the archive has exactly one top-level directory.
tar -C "$(dirname "$PREFIX")" -czf "$DIST/$TOOL-$VERSION-$PLATFORM.tar.gz" "$(basename "$PREFIX")"
echo "package: dist/$TOOL-$VERSION-$PLATFORM.tar.gz"
