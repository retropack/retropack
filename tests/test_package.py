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
               PLATFORM="linux-x86_64", PREFIX=str(prefix), SRC=str(src))
    return env, prefix


def run(tmp_path, env):
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)


def test_package_succeeds_and_ships_licence_and_notice(tmp_path):
    env, prefix = make_env(tmp_path)
    r = run(tmp_path, env)
    assert r.returncode == 0, r.stderr
    dist = REPO / "dist" / "cc65-2.19-linux-x86_64.tar.gz"
    assert dist.exists()
    with tarfile.open(dist) as tf:
        names = tf.getnames()
        assert "cc65-2.19/LICENSE" in names, names
        assert "cc65-2.19/RETROPACK-NOTICE" in names, names
        notice = tf.extractfile("cc65-2.19/RETROPACK-NOTICE").read().decode()
    # §7.3: exact source tag — cc65 tags are V<version>, not v<version>
    assert "(tag V2.19)" in notice, notice
    dist.unlink()


def test_package_fails_when_licence_missing(tmp_path):
    env, prefix = make_env(tmp_path, license_in_src=False)
    r = run(tmp_path, env)
    assert r.returncode != 0, "archive must not be produced without upstream LICENSE"
    assert not (REPO / "dist" / "cc65-2.19-linux-x86_64.tar.gz").exists()
