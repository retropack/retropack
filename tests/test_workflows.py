import pathlib, yaml

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"

def _on(data):
    """'on' parses as True under YAML 1.1; accept either key."""
    return data.get("on", data.get(True))

def test_every_workflow_parses_and_has_on_key():
    files = sorted(WF.glob("*.yml"))
    assert len(files) >= 3
    for f in files:
        data = yaml.safe_load(f.read_text())
        assert _on(data) is not None, f

def test_build_yml_contract():
    build = yaml.safe_load((WF / "build.yml").read_text())
    on = _on(build)
    assert "workflow_call" in on
    assert set(on["workflow_call"]["inputs"]) == {"tool", "version"}

def test_watch_triggers_and_keepalive():
    text = (WF / "watch.yml").read_text()
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "workflows/watch.yml/enable" in text   # §8.3 keep-alive
    assert "if: always()" in text                 # keep-alive step is unconditional

def test_release_stub_contract():
    # Task 5's stub (created later in this task's file set? no — templates).
    # Guard: brain build.yml is referenced from the template stub once it exists.
    stub = pathlib.Path(__file__).resolve().parent.parent / "templates" / "tool-repo" / ".github" / "workflows" / "release.yml"
    if stub.exists():
        assert "retropack/retropack/.github/workflows/build.yml@main" in stub.read_text()

def _steps(workflow, job):
    return workflow["jobs"][job].get("steps", [])

def test_prepare_declares_every_consumed_output():
    build = yaml.safe_load((WF / "build.yml").read_text())
    declared = set(build["jobs"]["prepare"].get("outputs", {}))
    text = (WF / "build.yml").read_text()
    import re
    consumed = set(re.findall(r"needs\.prepare\.outputs\.(\w+)", text))
    assert consumed <= declared, f"undeclared outputs consumed: {consumed - declared}"
    assert {"skip", "matrix", "platform_independent", "timeout"} <= declared

def test_prepare_matrix_shape_has_runner_and_platform():
    # §9.2: matrix must carry a runner (build uses matrix.runner) and the
    # noarch fan-out must be representable (platform_independent output).
    build = yaml.safe_load((WF / "build.yml").read_text())
    manifest_step = [s for s in _steps(build, "prepare") if s.get("id") == "manifest"][0]
    run = manifest_step["run"]
    assert '"runner"' in run and '"platform"' in run, "matrix entries must include runner+platform"
    assert "timeout_minutes" in run, "timeout output must come from the manifest"
    assert "platform_independent" in run

def test_build_jobs_checkout_brain_repo():
    # Reusable workflow runs in the caller (tool repo) context — jobs that need
    # tools//scripts must explicitly check out retropack/retropack (spec §9.2).
    build = yaml.safe_load((WF / "build.yml").read_text())
    for job in ("prepare", "build", "publish", "accept"):
        checkouts = [s for s in _steps(build, job)
                     if str(s.get("uses", "")).startswith("actions/checkout")]
        assert checkouts, f"job {job} needs a checkout"
        for s in checkouts:
            repo = (s.get("with") or {}).get("repository")
            assert repo == "retropack/retropack", (
                f"{job}: checkout defaults to the caller repo; "
                f"needs repository: retropack/retropack (got {repo!r})")
