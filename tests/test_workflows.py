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
    # security review P1: workflow_call needs its own publish flag — with only
    # tool/version declared, the publish/accept gates were trigger-dependent.
    assert set(on["workflow_call"]["inputs"]) == {"tool", "version", "publish"}
    assert on["workflow_call"]["inputs"]["publish"]["type"] == "boolean"
    assert on["workflow_call"]["inputs"]["publish"]["default"] is True
    assert set(on["workflow_dispatch"]["inputs"]) == {"tool", "version", "publish"}

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

def _runs(job):
    return "\n".join(str(s.get("run", "")) for s in job.get("steps", []))

def test_build_yml_dispatch_trigger_for_direct_runs():
    # workflow_call stays the spec path (tool repos); workflow_dispatch lets a
    # maintainer run the pipeline straight from the brain for development.
    build = yaml.safe_load((WF / "build.yml").read_text())
    on = _on(build)
    assert "workflow_call" in on and "workflow_dispatch" in on
    di = on["workflow_dispatch"]["inputs"]
    assert set(di) == {"tool", "version", "publish"}
    assert di["publish"]["type"] == "boolean"
    assert di["publish"]["default"] is False   # direct runs must not publish by default

def test_build_yml_pipeline_steps_present():
    # §9.2.2: every stage of the local-proven pipeline must be wired.
    build = yaml.safe_load((WF / "build.yml").read_text())
    b = _runs(build["jobs"]["build"])
    for frag in ("scripts/fetch-source.sh", "scripts/build-linux.sh",
                 "scripts/build-macos.sh", "tools/$TOOL/test.sh",
                 "scripts/check-portability.sh", "scripts/package.sh"):
        assert frag in b, f"build job missing: {frag}"
    # The noarch branch must honour build.sh's #!/usr/bin/env bash shebang —
    # `sh script.sh` picks dash on Ubuntu (set: Illegal option -o pipefail),
    # which is exactly how the first kickc CI run died.
    assert 'sh "tools/$TOOL/build.sh"' not in b
    assert '"tools/$TOOL/build.sh"' in b
    up = [s for s in _steps(build, "build")
          if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert up, "build job must upload artifacts"
    assert "dist-" in up[0]["with"]["name"]              # §9.2.2 dist-<platform>
    assert int(up[0]["with"]["retention-days"]) <= 7      # releases are the durable store
    # §6.1 env contract: build.sh runs under set -u and reads CFLAGS/LDFLAGS
    # even on paths where no wrapper sets them (macos, noarch) — default them.
    assert "LDFLAGS" in b and "CFLAGS" in b
    # Platforms are independent — one failure must not cancel the other legs,
    # or a red run tells you nothing about the remaining platforms.
    assert build["jobs"]["build"]["strategy"].get("fail-fast") is False
    assert build["jobs"]["accept"]["strategy"].get("fail-fast") is False

def test_build_yml_publish_job_flow():
    # §9.2.3: download → assets (fan-out + checksums) → attest → upload → release.
    build = yaml.safe_load((WF / "build.yml").read_text())
    p = build["jobs"]["publish"]
    uses = [str(s.get("uses", "")) for s in p["steps"]]
    assert any(u.startswith("actions/download-artifact") for u in uses)
    assert any(u.startswith("actions/attest-build-provenance") for u in uses)
    runs = _runs(p)
    for phase in ("publish.sh assets", "publish.sh upload", "publish.sh release"):
        assert phase in runs, f"publish job missing: {phase}"
    # attestation must come before the release becomes visible (§7.4 order)
    step_names = [s.get("name", "") for s in p["steps"]]
    assert step_names.index("attest build provenance") < step_names.index("publish release")

def test_build_yml_accept_job_installs_via_mise():
    # §9.2.4: mise from mise.run, install with MISE_GITHUB_TOKEN, test with mise where.
    # The token lives in step env (never interpolated into run: — see the
    # no-gh-expressions test), so search the whole job definition.
    build = yaml.safe_load((WF / "build.yml").read_text())
    a = str(build["jobs"]["accept"])
    for frag in ("mise.run", "mise install", "MISE_GITHUB_TOKEN", "mise where"):
        assert frag in a, f"accept job missing: {frag}"

def test_build_yml_on_failure_opens_issue():
    # §9.2.5/§8.1: issue titled "build failure: <tool> <version>", label build-failure.
    build = yaml.safe_load((WF / "build.yml").read_text())
    f = build["jobs"]["on-failure"]
    assert "failure()" in str(f["if"])
    runs = _runs(f)
    for frag in ("build-failure", "gh issue", "build failure:", "acceptance failure:"):
        assert frag in runs, f"on-failure missing: {frag}"
    # No checkout in this job — gh must get the repo explicitly, it cannot
    # infer it from a git remote (first real run died on "not a git repository").
    assert runs.count("--repo \"$GITHUB_REPOSITORY\"") >= 2

# --- security review contracts (pre-E2E hardening) ---

REPO = pathlib.Path(__file__).resolve().parent.parent

def _load(name):
    return yaml.safe_load((WF / name).read_text())

def test_permissions_are_least_privilege_per_job():
    # build.yml must hold NO workflow-level permissions; each job requests
    # exactly what it needs (P1: upstream build code ran with write+id-token).
    build = _load("build.yml")
    assert "permissions" not in build, "build.yml must scope permissions per job"
    expected = {
        "prepare": {"contents": "read"},
        "build": {"contents": "read"},
        "publish": {"contents": "write", "id-token": "write", "attestations": "write"},
        "accept": {"contents": "read"},
        "on-failure": {"issues": "write"},
    }
    for job, perms in expected.items():
        assert build["jobs"][job].get("permissions") == perms, \
            f"{job}: {build['jobs'][job].get('permissions')!r} != {perms!r}"

    watch = _load("watch.yml")
    assert watch.get("permissions") == {"contents": "read"}
    assert watch["jobs"]["keep-alive"].get("permissions") == {"actions": "write"}
    # dispatch + propose act through the per-repo App token; the GITHUB_TOKEN
    # must NOT gain write scopes for them
    assert "permissions" not in watch["jobs"]["dispatch"]
    assert "permissions" not in watch["jobs"]["propose"]

    ci = _load("ci.yml")
    assert ci.get("permissions") == {"contents": "read"}

def test_checkouts_never_persist_credentials():
    # Credentials live in .git/config and are readable by every command a job
    # runs — including the containerised upstream build.
    for name in ("build.yml", "watch.yml", "ci.yml"):
        wf = _load(name)
        for jname, job in wf["jobs"].items():
            for s in job.get("steps", []):
                if str(s.get("uses", "")).startswith("actions/checkout"):
                    assert (s.get("with") or {}).get("persist-credentials") is False, \
                        f"{name}:{jname} checkout persists credentials"

def test_no_gh_expressions_in_run_blocks():
    # ${{ }} inside run: interpolates values into shell source — for
    # workflow_dispatch inputs that is code injection (watch.yml). env:/with:
    # are the safe indirection; github.token belongs in env too.
    for f in sorted(WF.glob("*.yml")):
        wf = yaml.safe_load(f.read_text())
        for jname, job in wf["jobs"].items():
            for s in job.get("steps", []):
                r = s.get("run")
                if r:
                    assert "${{" not in r, \
                        f"{f.name}:{jname}: GH expression in run: {r.splitlines()[0][:60]!r}"

def test_prepare_validates_inputs():
    # tool/version enter via workflow_dispatch (and later the watcher) —
    # validate format at the trust boundary before anything consumes it.
    build = _load("build.yml")
    steps = build["jobs"]["prepare"]["steps"]
    val = [s for s in steps if s.get("name") == "validate inputs"]
    assert val, "prepare must validate inputs before use"
    run = val[0]["run"]
    assert "'^[a-z0-9-]+$'" in run
    assert "'^[0-9]+(\\.[0-9]+)*$'" in run

def test_watch_yml_pins_review_gate():
    # §8.1 review gate: only pinned versions dispatch; unpinned ones are
    # hashed by the watcher and proposed as one pins PR per tool — the merge
    # authorizes the build, never the schedule.
    watch = _load("watch.yml")
    declared = set(watch["jobs"]["detect"].get("outputs", {}))
    assert {"pending", "tools", "unpinned"} <= declared
    prop = watch["jobs"]["propose"]
    assert "unpinned != '{}'" in str(prop["if"])
    assert "dry_run" in str(prop["if"])          # dry-run = zero side effects
    text = (WF / "watch.yml").read_text()
    for frag in ("--write-pins", "--body-dir", "permission-pull-requests: write",
                 "watch/pins-", "gh pr create", "gh pr edit"):
        assert frag in text, f"watch.yml propose job missing: {frag}"
    # detect's dispatch outputs must come from the dispatch bucket — a slip
    # here would route unreviewed versions straight to builds
    run = _runs(watch["jobs"]["detect"])
    assert "['dispatch']" in run and "['propose']" in run

def test_no_jq_program_interpolation():
    # Values must enter jq/awk as data (-v/--arg), never inside the program
    # text — a crafted version could otherwise steer the draft-id query that
    # feeds release deletion.
    text = (WF / "build.yml").read_text() + (REPO / "scripts" / "publish.sh").read_text()
    assert "select(.tag_name ==" not in text
    assert "select(.title ==" not in text
