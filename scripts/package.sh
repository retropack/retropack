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
# DIST is overridable so tests never write into (or delete) the real dist/.
DIST="${DIST:-$REPO_ROOT/dist}"
mkdir -p "$DIST"

# PREFIX is <work>/<tool>-<version>/ — but it may be owned by the build
# container's root (CI runners use rootful docker; local rootless docker
# maps root to the invoking user, which is why this only bit in CI). Stage a
# writable copy before adding the licence/notice files so packaging never
# depends on who ran the build.
[ -d "$PREFIX" ] || { echo "package: PREFIX $PREFIX does not exist" >&2; exit 1; }
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
BASE=$(basename "$PREFIX")
cp -r "$PREFIX" "$STAGE/$BASE"
DEST="$STAGE/$BASE"
# The copy inherits the source's mode (e.g. 555) — make our own copy writable.
chmod u+w "$DEST"

# Copy upstream licence files (paths relative to source tree) into the prefix.
# Spec §2.1/§7.2: every archive ships the upstream LICENSE — a missing one is a
# packaging failure, never a warning.
[ -n "${SRC:-}" ] || { echo "package: SRC must be set to locate licence files" >&2; exit 1; }
while IFS= read -r lic; do
  [ -f "$SRC/$lic" ] || { echo "package: licence file $lic not found in SRC — refusing to ship without it" >&2; exit 1; }
  cp "$SRC/$lic" "$DEST/"
done < <(python3 - "$MANIFEST" <<'PY'
import tomllib, sys
t = tomllib.load(open(sys.argv[1], "rb"))
for f in t["tool"].get("license_files", []):
    print(f)
PY
)

# Generate RETROPACK-NOTICE from the template (spec §7.3).
# Provenance URL: prefer the EFFECTIVE url recorded by fetch-source (exact
# file shipped — matters for repackage mode's redirected asset links);
# fall back to the manifest's version-templated URL.
RECORDED_SOURCE_URL=""
if [ -n "${WORK:-}" ] && [ -f "$WORK/.source-url" ]; then
  RECORDED_SOURCE_URL="$(head -n1 "$WORK/.source-url")"
fi
python3 - "$MANIFEST" "$VERSION" "$PLATFORM" "$REPO_ROOT/templates/RETROPACK-NOTICE.tmpl" "$DEST/RETROPACK-NOTICE" "$RECORDED_SOURCE_URL" <<'PY'
import os, sys, tomllib, datetime
manifest, version, platform, tmpl_path, out_path = sys.argv[1:6]
recorded = sys.argv[6] if len(sys.argv) > 6 else ""
t = tomllib.load(open(manifest, "rb"))
tool = t["tool"]
up = t["upstream"]
notice = open(tmpl_path).read()

# Exact source tag (§7.3): derive from the manifest URL, not a v-prefix guess.
# github:   .../archive/refs/tags/V2.19.tar.gz  → V2.19
# gitlab:   .../-/archive/0.8.6/kickc-0.8.6.tar.gz → 0.8.6
# sourceforge: no tag — the release filename IS the source identity.
manifest_url = t["source"]["url"].replace("{version}", version)
source_url = recorded or manifest_url
source_ref = manifest_url
if "/refs/tags/" in source_ref:
    source_tag = source_ref.split("/refs/tags/", 1)[1].removesuffix(".tar.gz")
elif "/-/archive/" in source_ref:
    source_tag = source_ref.split("/-/archive/", 1)[1].split("/", 1)[0]
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
    # Repackage honesty (security review F2): the attestation proves "this
    # workflow produced these bytes", which for repackage tools means
    # "repackaged upstream prebuilt binaries" — say so in the shipped notice.
    "build_mode": ("source — compiled from upstream source by this pipeline"
                   if t["build"].get("mode", "source") == "source"
                   else "repackage — upstream prebuilt binaries repackaged as-is "
                        "(NOT compiled by retropack)"),
    "patches": patches_field,
    "platform": platform,
    "build_date": datetime.date.today().isoformat(),
    "run_url": (
        os.environ["GITHUB_SERVER_URL"] + "/" + os.environ["GITHUB_REPOSITORY"]
        + "/actions/runs/" + os.environ["GITHUB_RUN_ID"]
        if os.environ.get("GITHUB_RUN_ID") else "n/a (local build)"),
    "runtime_requirements": ", ".join(tool.get("runtime_requirements", [])) or "none",
}.items():
    notice = notice.replace("{{%s}}" % field, value)
open(out_path, "w").write(notice)
PY

# Exactly one top-level directory → mise auto-applies strip_components=1 (§7.2).
tar -C "$STAGE" -czf "$DIST/$TOOL-$VERSION-$PLATFORM.tar.gz" "$BASE"
echo "package: dist/$TOOL-$VERSION-$PLATFORM.tar.gz"
