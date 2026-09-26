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
