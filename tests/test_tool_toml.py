import tomllib, pathlib, re

TOOLS = sorted(pathlib.Path(__file__).resolve().parent.parent.glob("tools/*/tool.toml"))
REQUIRED_TOP = {"tool", "upstream", "source", "build", "test"}
REQUIRED_TOOL = {"name", "description", "homepage", "license", "license_files",
                 "platform_independent", "runtime_requirements"}
REQUIRED_UPSTREAM = {"type", "repo", "tag_regex", "min_version", "skip_versions", "max_per_run"}
VALID_TYPES = {"github", "gitlab", "sourceforge"}
VALID_MODES = {"source", "repackage"}

def test_at_least_five_tools():
    assert len(TOOLS) >= 5

def test_schema_and_invariants():
    for path in TOOLS:
        data = tomllib.loads(path.read_text())
        assert REQUIRED_TOP <= set(data), path
        assert REQUIRED_TOOL <= set(data["tool"]), path
        assert REQUIRED_UPSTREAM <= set(data["upstream"]), path
        assert data["tool"]["name"] == path.parent.name, path
        assert data["upstream"]["type"] in VALID_TYPES, path
        assert data["build"]["mode"] in VALID_MODES, path
        # version named group is mandatory (spec §5)
        assert "version" in re.compile(data["upstream"]["tag_regex"]).groupindex, path
        assert isinstance(data["upstream"]["max_per_run"], int), path
        # sf-only key, when present, must also carry the version group
        if "file_regex" in data["upstream"]:
            assert "version" in re.compile(data["upstream"]["file_regex"]).groupindex, path
