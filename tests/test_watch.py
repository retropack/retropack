import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location(
    "watch", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

def test_parse_tags_extracts_version_group():
    assert watch.parse_tags(["V2.19", "V2.18", "junk"], r"^V(?P<version>\d+\.\d+(?:\.\d+)?)$") == ["2.19", "2.18"]

def test_parse_tags_missing_group_skips_not_crash():
    # Plan Review Focus: a tag_regex without a version group must not abort
    # the daily watch run — skip the tool instead of raising.
    assert watch.parse_tags(["V2.19"], r"^V(\d+\.\d+)$") == []

def test_compare_versions_numeric_tuples():
    assert watch.compare_versions("2.19", "2.18") > 0
    assert watch.compare_versions("2.19", "2.19.1") < 0
    assert watch.compare_versions("2.19.0", "2.19") == 0
    assert watch.compare_versions("4.4.0", "4.10.0") < 0

def test_compare_versions_string_segments_after_numeric():
    assert watch.compare_versions("2.19rc1", "2.19") > 0   # non-numeric vs missing → string beats empty
    assert watch.compare_versions("2.19rc1", "2.19rc2") < 0

def test_select_pending_caps_newest_first():
    up = ["1.60", "1.59.3121", "1.59.3120"]
    assert watch.select_pending(up, released=["1.60"], blocked=[], max_per_run=2) == ["1.59.3121", "1.59.3120"]

def test_select_pending_excludes_blocked():
    assert watch.select_pending(["3.0", "2.0"], released=[], blocked=["3.0"], max_per_run=5) == ["2.0"]

def test_select_pending_dedupes_equivalent_versions():
    # "2.19" and "2.19.0" compare equal (spec §5) — a released 2.19 must
    # block a pending 2.19.0 or we double-publish the same release.
    assert watch.select_pending(["2.19.0", "2.18"], released=["2.19"],
                                blocked=[], max_per_run=5) == ["2.18"]
    assert watch.select_pending(["3.0.0"], released=[], blocked=["3.0"],
                                max_per_run=5) == []
    # but a genuinely newer patch release still passes through
    assert watch.select_pending(["3.0.1"], released=[], blocked=["3.0"],
                                max_per_run=5) == ["3.0.1"]

def test_main_stub_returns_zero():
    assert watch.main(["--dry-run"]) == 0
