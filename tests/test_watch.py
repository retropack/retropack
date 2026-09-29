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

# --- source-hash pins: the §8.1 review gate ---

def test_resolve_source_url_template_substitutes_version():
    cfg = {"build": {"mode": "source"},
           "source": {"url": "https://example.com/v{version}/src.tar.gz"}}
    assert watch.resolve_source_url(cfg, "2.19") == \
        "https://example.com/v2.19/src.tar.gz"

def test_resolve_source_url_repackage_resolves_gitlab_asset(monkeypatch):
    import json as _json
    class _R:
        def read(self):
            return _json.dumps([{"tag_name": "0.8.6", "assets": {"links": [
                {"name": "Binary", "url": "https://gitlab.com/x.zip"}]}}]).encode()
    monkeypatch.setattr(watch.urllib.request, "urlopen", lambda req, timeout: _R())
    cfg = {"build": {"mode": "repackage"},
           "upstream": {"type": "gitlab", "repo": "camelot/kickc"},
           "source": {"url": "https://example.com/src.tar.gz", "release_asset": "Binary"}}
    assert watch.resolve_source_url(cfg, "0.8.6") == "https://gitlab.com/x.zip"
    # non-gitlab repackage upstream is a manifest error, not a silent template
    cfg["upstream"] = {"type": "github", "repo": "o/r"}
    try:
        watch.resolve_source_url(cfg, "1.0")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")

def test_fetch_sha256_refuses_non_https_initial_url():
    # The digest lands in the reviewed pins file — a downgrade here poisons
    # the trust root, not just one build.
    for bad in ("http://example.com/x.tgz", "file:///etc/passwd"):
        try:
            watch.fetch_sha256(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")

def test_https_only_handler_blocks_redirect_downgrade():
    try:
        watch._HTTPSOnly().redirect_request(None, None, 302, "", {}, "http://evil/x")
    except ValueError:
        pass
    else:
        raise AssertionError("http redirect target allowed")

def test_pinned_versions_reads_file_and_tolerates_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_TOOLS_DIR", str(tmp_path))
    assert watch.pinned_versions("nope") == set()          # no file → ungated
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "source-sha256.txt").write_text("# comment\nabc  1.2.3\n\n")
    assert watch.pinned_versions("t") == {"1.2.3"}

def test_write_pins_creates_appends_and_is_idempotent(tmp_path):
    (tmp_path / "t1").mkdir()
    propose = {"t1": {"2.0": {"sha256": "bb", "url": "https://x/2"},
                      "1.0": {"sha256": "aa", "url": "https://x/1"}}}
    bodies = str(tmp_path / "bodies")
    touched = watch.write_pins(propose, None, bodies, tools_dir=str(tmp_path))
    assert touched == ["t1"]
    pins = (tmp_path / "t1" / "source-sha256.txt").read_text()
    assert "aa  1.0" in pins and "bb  2.0" in pins
    body = (tmp_path / "bodies" / "t1.md").read_text()
    assert "aa" in body and "https://x/2" in body      # reviewer gets hash + provenance
    # idempotent: the same propose adds nothing (daily re-hash before merge)
    assert watch.write_pins(propose, None, bodies, tools_dir=str(tmp_path)) == []
    # appending keeps existing pins; --write-pins TOOL filters
    more = {"t1": {"3.0": {"sha256": "cc", "url": "https://x/3"}},
            "t2": {"9.9": {"sha256": "dd", "url": "https://y/9"}}}
    (tmp_path / "t2").mkdir()
    assert watch.write_pins(more, "t1", bodies, tools_dir=str(tmp_path)) == ["t1"]
    pins = (tmp_path / "t1" / "source-sha256.txt").read_text()
    assert "aa  1.0" in pins and "cc  3.0" in pins
    assert not (tmp_path / "t2" / "source-sha256.txt").exists()

def test_detect_splits_dispatch_and_propose_at_the_pin_gate(tmp_path, monkeypatch):
    tool = tmp_path / "fake"
    tool.mkdir()
    (tool / "tool.toml").write_text(
        '[upstream]\ntype = "github"\nrepo = "o/r"\n'
        'tag_regex = "^(?P<version>[0-9.]+)$"\n'
        '[source]\nurl = "https://x/{version}.tar.gz"\n'
        '[build]\nmode = "source"\n')
    (tool / "source-sha256.txt").write_text("00  1.0\n")   # 1.0 reviewed, 2.0 not
    monkeypatch.setattr(watch, "_TOOLS_DIR", str(tmp_path))
    monkeypatch.setattr(watch, "upstream_versions", lambda t, cfg=None: ["1.0", "2.0"])
    monkeypatch.setattr(watch, "_github_get", lambda path: "[]")
    monkeypatch.setattr(watch, "fetch_sha256", lambda url: "ff" * 32)
    out = watch.detect()
    assert out["dispatch"] == {"fake": ["1.0"]}            # pinned → build
    assert out["propose"]["fake"]["2.0"]["sha256"] == "ff" * 32   # unpinned → PR
    assert out["propose"]["fake"]["2.0"]["url"] == "https://x/2.0.tar.gz"
    # a failed hash fetch skips that version but keeps the rest of the run
    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(watch, "fetch_sha256", boom)
    out = watch.detect()
    assert out["dispatch"] == {"fake": ["1.0"]} and out["propose"] == {}
    # forced build bypasses the gate entirely — the maintainer IS the review
    out = watch.detect("fake", "9.9")
    assert out == {"dispatch": {"fake": ["9.9"]}, "propose": {}}

def test_latest_flag_only_highest_wins():
    releases = [
        {"tag_name": "v4.6.0", "draft": False, "prerelease": False},
        {"tag_name": "v2.19", "draft": False, "prerelease": False},
        {"tag_name": "v9.9.9", "draft": True, "prerelease": False},   # drafts don't count
    ]
    assert watch.latest_flag("4.6.0", releases) == "true"    # highest published
    assert watch.latest_flag("2.19", releases) == "false"    # backfill must not steal latest (§7.4)
    # prereleases never count toward "highest"
    releases.append({"tag_name": "v5.0.0", "draft": False, "prerelease": True})
    assert watch.latest_flag("4.6.0", releases) == "true"

def test_highest_release_id_picks_id_of_top_published():
    import json as _json
    doc = _json.dumps([
        {"id": 397780317, "tag_name": "v1.57.2900", "draft": False, "prerelease": False},
        {"id": 397659279, "tag_name": "v1.60.3243", "draft": False, "prerelease": False},
        {"id": 111, "tag_name": "v9.9.9", "draft": True, "prerelease": False},
        {"id": 222, "tag_name": "v8.8.8", "draft": False, "prerelease": True},
        {"id": 333, "tag_name": "v1.59.3120", "draft": False, "prerelease": False},
    ])
    # highest PUBLISHED version is 1.60.3243 — NOT the newest-created 1.57,
    # not the draft, not the prerelease
    assert watch.highest_release_id(doc) == "397659279"
    assert watch.highest_release_id("[]") == ""
    assert watch.highest_release_id(
        _json.dumps([{"id": 5, "tag_name": "v2.0", "draft": True}])) == ""

def test_release_asset_url_selects_tag_and_link():
    import json as _json
    doc = _json.dumps([
        {"tag_name": "0.8.5", "assets": {"links": [
            {"name": "Binary", "url": "https://bit.ly/older"}]}},
        {"tag_name": "0.8.6", "assets": {"links": [
            {"name": "Binary", "url": "https://bit.ly/newer"},
            {"name": "Other", "url": "https://example.com/x"}]}},
    ])
    assert watch.release_asset_url(doc, "0.8.6", "Binary") == "https://bit.ly/newer"
    assert watch.release_asset_url(doc, "0.8.6", "Other") == "https://example.com/x"
    # loud failures (fetch-source turns them into build errors)
    for bad in (("0.9.0", "Binary"), ("0.8.5", "Missing")):
        try:
            watch.release_asset_url(doc, *bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")

def test_released_from_api_strips_v_skips_draft_and_prerelease():
    import json as _json
    api = _json.dumps([
        {"tag_name": "v2.19", "draft": False, "prerelease": False},
        {"tag_name": "v9.9.9", "draft": True, "prerelease": False},
        {"tag_name": "v8.8.8", "draft": False, "prerelease": True},
        {"tag_name": "v2.18", "draft": False, "prerelease": False},
    ])
    assert watch.released_from_api(api) == ["2.19", "2.18"]

def test_blocked_from_issues_parses_both_title_kinds():
    import json as _json
    issues = _json.dumps([
        {"title": "build failure: tass64 1.58.2974", "number": 1},
        {"title": "acceptance failure: tass64 1.57.2900", "number": 2},
        {"title": "build failure: sdcc 4.6.0", "number": 3},          # other tool
        {"title": "kickc: some unrelated discussion", "number": 4},
        {"pull_request": {}, "title": "build failure: tass64 9.9.9", "number": 5},  # PR, not issue
    ])
    assert watch.blocked_from_issues(issues, "tass64") == ["1.58.2974", "1.57.2900"]
    assert watch.blocked_from_issues(issues, "sdcc") == ["4.6.0"]
    assert watch.blocked_from_issues(issues, "kickc") == []

def test_eligible_filters_min_and_skip():
    # detect() keeps ALL pending versions (not just the latest) — the min/skip
    # policy must still apply to every one of them (spec §5).
    out = watch.eligible(["1.58.2974", "1.59.3120", "1.60.3243"],
                         min_version="1.59.3120", skip_versions=[])
    assert out == ["1.59.3120", "1.60.3243"]
    assert watch.eligible(["1.59.3120"], "1.59.3120", ["1.59.3120"]) == []

# --- latest-version resolution (local-build default) ---

def test_pick_latest_respects_min_and_skip():
    assert watch.pick_latest(["1.59.3121", "1.59.3120", "1.58.0"],
                             min_version="1.59.3120",
                             skip_versions=["1.59.3121"]) == "1.59.3120"
    assert watch.pick_latest(["4.4.0", "4.10.0"]) == "4.10.0"
    assert watch.pick_latest(["2.18"], min_version="2.19") is None
    assert watch.pick_latest([]) is None

def test_parse_lsremote_extracts_tags():
    text = ("abc123\trefs/tags/V2.19\n"
            "abc124\trefs/tags/V2.18\n"
            "abc125\trefs/tags/not-a-version\n")
    assert watch.parse_lsremote(text, r"^V(?P<version>\d+\.\d+(?:\.\d+)?)$") \
        == ["2.19", "2.18"]

def test_parse_sourceforge_collects_filenames_from_best_release_and_rss():
    import json as _json
    best = _json.dumps({"release": {"filename": "64tass-1.59.3120-src.zip",
                                     "url": "https://sf.example/x/download"}})
    # Real SF RSS wraps titles in CDATA and prefixes the project path
    # (this is what shipped: the unwrapped form never matched file_regex).
    rss = ("<rss><channel>"
           "<item><title><![CDATA[/source/64tass-1.59.3119-src.zip]]></title></item>"
           "<item><title><![CDATA[/source/64tass-1.58.2974-src.zip]]></title></item>"
           "<item><title>tass64/source (folder)</title></item>"
           "</channel></rss>")
    names = watch.parse_sourceforge(best, rss)
    assert "64tass-1.59.3120-src.zip" in names
    assert "64tass-1.59.3119-src.zip" in names   # CDATA + path prefix stripped
    assert "64tass-1.58.2974-src.zip" in names
    # composing with the manifest's file_regex yields normalized versions
    versions = watch.parse_tags(
        names, r"^64tass-(?P<version>\d+\.\d+\.\d+)-src\.zip$")
    assert set(versions) >= {"1.59.3120", "1.59.3119", "1.58.2974"}
