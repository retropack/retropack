"""Local, network-free extraction tests for scripts/fetch-source.sh (spec §5, §10).

Covers the tass64 case: a ZIP whose URL does not end in .zip (`...src.zip/download`).
"""
import os, pathlib, subprocess, tarfile, zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "fetch-source.sh"


def run_fetch(tmp_path, url, tool, version, strip_from_manifest=True):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    env = dict(os.environ, TOOL=tool, VERSION=version,
               WORK=str(work), SRC_URL=url)
    # Don't inherit a caller's SRC (e.g. a just-run local build exports it):
    # fetch-source.sh honors SRC over $WORK/src and would extract into it.
    env.pop("SRC", None)
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_zip_url_not_ending_in_zip_is_extracted(tmp_path):
    z = tmp_path / "download"          # URL path ends in /download, like SourceForge
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("64tass-src/README", "hi")
    r = run_fetch(tmp_path, f"file://{z}", "tass64", "1.59.3121")
    assert r.returncode == 0, r.stderr
    src = tmp_path / "work" / "src"
    # strip_components = 1 for tass64 → top dir stripped, README at SRC root
    assert (src / "64tass-src" / "README").exists() or (src / "README").exists(), \
        f"nothing extracted: {list(src.rglob('*'))}; stderr={r.stderr}"


def test_targz_with_strip_components(tmp_path):
    tgz = tmp_path / "src.tar.gz"
    with tarfile.open(tgz, "w:gz") as tf:
        payload = tmp_path / "hello.c"
        payload.write_text("int x;\n")
        tf.add(payload, arcname="V2.19/hello.c")
    r = run_fetch(tmp_path, f"file://{tgz}", "cc65", "2.19")
    assert r.returncode == 0, r.stderr
    # strip_components = 1 for cc65 (spec §5) → top dir stripped
    assert (tmp_path / "work" / "src" / "hello.c").exists(), \
        f"strip failed: {list((tmp_path / 'work' / 'src').rglob('*'))}"

def test_tarbz2_with_strip_components(tmp_path):
    # sdcc ships .tar.bz2 exclusively (verified: .tar.gz 404s for 4.4.0–4.6.0)
    tbz = tmp_path / "src.tar.bz2"
    with tarfile.open(tbz, "w:bz2") as tf:
        payload = tmp_path / "hello.c"
        payload.write_text("int x;\n")
        tf.add(payload, arcname="sdcc-4.6.0/hello.c")
    r = run_fetch(tmp_path, f"file://{tbz}", "sdcc", "4.6.0")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "work" / "src" / "hello.c").exists(), \
        f"bz2 extract failed: {r.stderr}"

def _fragment_from_patch() -> str:
    """Original-side content of the real version-scoped patch (context + '-' lines)."""
    patch = (REPO / "tools" / "tass64" / "patches" / "1.59.3120" /
             "0001-rename-static-memalign.patch").read_text()
    lines = []
    for ln in patch.splitlines():
        if ln.startswith("---") or ln.startswith("+++") or ln.startswith("@@"):
            continue
        if ln.startswith("-") or ln.startswith(" "):
            lines.append(ln[1:])
    return "\n".join(lines) + "\n"

def _make_src_zip(tmp_path, content: str) -> str:
    import zipfile
    z = tmp_path / "src.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("pkg/64tass.c", content)
        zf.writestr("pkg/Makefile", "all:\n\t@true\n")
    return f"file://{z}"

def test_version_scoped_patches_apply_only_to_their_version(tmp_path):
    # tools/<tool>/patches/<version>/ holds patches for that version ONLY —
    # tass64's memalign rename exists in 1.59.3120 and nowhere else.
    original = _fragment_from_patch()
    assert "static address_t memalign(" in original

    r159 = run_fetch(tmp_path, _make_src_zip(tmp_path, original),
                     "tass64", "1.59.3120")
    assert r159.returncode == 0, r159.stderr
    applied = (tmp_path / "work" / "src" / "64tass.c").read_text()
    assert "static address_t v_memalign(" in applied, "version-scoped patch not applied"
    assert "static address_t memalign(" not in applied

    # Same source fetched as a different version: directory must be skipped.
    import shutil
    shutil.rmtree(tmp_path / "work")
    r160 = run_fetch(tmp_path, _make_src_zip(tmp_path, original),
                     "tass64", "1.60.3243")
    assert r160.returncode == 0, r160.stderr
    untouched = (tmp_path / "work" / "src" / "64tass.c").read_text()
    assert "static address_t memalign(" in untouched, "patch must not leak to other versions"
