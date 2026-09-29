"""Filesystem tests for scripts/package.sh (spec §7.2, §7.3)."""
import os, pathlib, subprocess, tarfile, tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "package.sh"


def make_env(tmp_path, license_in_src=True):
    prefix = tmp_path / "work" / "cc65-2.19"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "cc65").write_text("#!/bin/sh\n")
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    if license_in_src:
        (src / "LICENSE").write_text("Zlib licence text\n")
    env = dict(os.environ, TOOL="cc65", VERSION="2.19",
               PLATFORM="linux-x86_64", PREFIX=str(prefix), SRC=str(src),
               DIST=str(tmp_path / "dist"))
    return env, prefix


def run(tmp_path, env):
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_package_succeeds_and_ships_licence_and_notice(tmp_path):
    env, prefix = make_env(tmp_path)
    r = run(tmp_path, env)
    assert r.returncode == 0, r.stderr
    dist = tmp_path / "dist" / "cc65-2.19-linux-x86_64.tar.gz"
    assert dist.exists()
    with tarfile.open(dist) as tf:
        names = tf.getnames()
        assert "cc65-2.19/LICENSE" in names, names
        assert "cc65-2.19/RETROPACK-NOTICE" in names, names
        notice = tf.extractfile("cc65-2.19/RETROPACK-NOTICE").read().decode()
    # §7.3: exact source tag — cc65 tags are V<version>, not v<version>
    assert "(tag V2.19)" in notice, notice
    assert "compiled from upstream source" in notice, notice
    dist.unlink()


def test_package_fails_when_licence_missing(tmp_path):
    env, prefix = make_env(tmp_path, license_in_src=False)
    r = run(tmp_path, env)
    assert r.returncode != 0, "archive must not be produced without upstream LICENSE"
    assert not (tmp_path / "dist" / "cc65-2.19-linux-x86_64.tar.gz").exists()

def test_package_prefers_recorded_source_url(tmp_path):
    # Repackage builds download a per-version asset (GitLab wiki upload behind
    # a redirect) — fetch-source records the effective URL and the notice must
    # cite THAT, while the tag still derives from the manifest pattern.
    import os, tarfile
    prefix = tmp_path / "work" / "kickc-0.8.6"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "kickc").write_text("#!/bin/sh\n")
    src = tmp_path / "src"
    src.mkdir()
    (src / "LICENSE.txt").write_text("MIT\n")
    work = tmp_path / "work"
    (work / ".source-url").write_text(
        "https://gitlab.com/camelot/kickc/-/wikis/uploads/abc123/kickc_0.8.6.zip\n")
    env = dict(os.environ, TOOL="kickc", VERSION="0.8.6", PLATFORM="noarch",
               PREFIX=str(prefix), SRC=str(src), WORK=str(work),
               DIST=str(tmp_path / "dist"))
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    with tarfile.open(tmp_path / "dist" / "kickc-0.8.6-noarch.tar.gz") as tf:
        notice = tf.extractfile("kickc-0.8.6/RETROPACK-NOTICE").read().decode()
    assert "wikis/uploads/abc123/kickc_0.8.6.zip" in notice, notice
    assert "(tag 0.8.6)" in notice, notice   # tag still from the manifest pattern
    # F2: repackage must not masquerade as a build — attestation covers the
    # pipeline, and the notice states the bytes are upstream's prebuilt jars
    assert "prebuilt binaries repackaged as-is" in notice, notice

def test_package_handles_readonly_prefix(tmp_path):
    # CI builds run in rootful docker → $PREFIX is root:root 755 while the
    # packaging step runs as the unprivileged runner (first real run died on
    # 'cp: Permission denied'). Packaging must not depend on who built it.
    import os, tarfile
    env, prefix = make_env(tmp_path)
    os.chmod(prefix, 0o555)
    try:
        r = run(tmp_path, env)
        assert r.returncode == 0, r.stderr
    finally:
        os.chmod(prefix, 0o755)
    dist = tmp_path / "dist" / "cc65-2.19-linux-x86_64.tar.gz"
    assert dist.exists()
    with tarfile.open(dist) as tf:
        names = tf.getnames()
        assert "cc65-2.19/LICENSE" in names, names
        assert "cc65-2.19/RETROPACK-NOTICE" in names, names
