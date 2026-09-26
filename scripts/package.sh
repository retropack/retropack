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
# Spec §2.1/§7.2: every archive ships the upstream LICENSE — a missing one is a
# packaging failure, never a warning.
[ -n "${SRC:-}" ] || { echo "package: SRC must be set to locate licence files" >&2; exit 1; }
while IFS= read -r lic; do
  [ -f "$SRC/$lic" ] || { echo "package: licence file $lic not found in SRC — refusing to ship without it" >&2; exit 1; }
  cp "$SRC/$lic" "$PREFIX/"
done < <(python3 - "$MANIFEST" <<'PY'
import tomllib, sys
t = tomllib.load(open(sys.argv[1], "rb"))
for f in t["tool"].get("license_files", []):
    print(f)
PY
)

# Generate RETROPACK-NOTICE from the template (spec §7.3).
python3 - "$MANIFEST" "$VERSION" "$PLATFORM" "$REPO_ROOT/templates/RETROPACK-NOTICE.tmpl" "$PREFIX/RETROPACK-NOTICE" <<'PY'
import os, sys, tomllib, datetime
manifest, version, platform, tmpl_path, out_path = sys.argv[1:6]
t = tomllib.load(open(manifest, "rb"))
tool = t["tool"]
up = t["upstream"]
notice = open(tmpl_path).read()

# Exact source tag (§7.3): derive from the manifest URL, not a v-prefix guess.
# github:   .../archive/refs/tags/V2.19.tar.gz  → V2.19
# gitlab:   .../-/archive/0.8.6/kickc-0.8.6.tar.gz → 0.8.6
# sourceforge: no tag — the release filename IS the source identity.
source_url = t["source"]["url"].replace("{version}", version)
if "/refs/tags/" in source_url:
    source_tag = source_url.split("/refs/tags/", 1)[1].removesuffix(".tar.gz")
elif "/-/archive/" in source_url:
    source_tag = source_url.split("/-/archive/", 1)[1].split("/", 1)[0]
else:
    # SourceForge /download URLs: filename before the trailing /download
    parts = source_url.rstrip("/").split("/")
    source_tag = parts[-2] if parts[-1] == "download" else parts[-1]

patches_dir = os.path.join(os.path.dirname(manifest), "patches")
patches = sorted(os.listdir(patches_dir)) if os.path.isdir(patches_dir) else []
patches_field = ", ".join(patches) if patches else "none"
if patches:
    # §7.3: link applied patches to the brain commit that contains them.
    sha = os.environ.get("GITHUB_SHA", "")
    if sha:
        patches_field += f" (retropack/retropack@{sha})"

for field, value in {
    "tool": tool["name"],
    "version": version,
    "homepage": tool.get("homepage", ""),
    "source_url": source_url,
    "source_tag": source_tag,
    "license": tool.get("license", ""),
    "patches": patches_field,
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
