# retropack Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the complete `retropack/retropack` brain-repo skeleton — directory layout, tool manifests, script stubs, workflow files, templates, and tests — so that M1 end-to-end implementation has every file and contract in place and CI (shellcheck, python tests, tool.toml schema) is green from day one.

**Architecture:** One git repo at the project root containing `tools/<name>/` (manifest + build/test scripts + fixtures), `scripts/` (shared shell wrappers + `watch.py`), `templates/` (tool-repo + notice), and `.github/workflows/` (watch/build/ci). Scripts that need live network/GitHub context (dispatch, publish, docker builds) are contract-documented stubs; pure logic (`watch.py` version parsing/comparison/selection, tool.toml schema) is fully implemented and tested now.

**Tech Stack:** Bash (shellcheck-clean), Python 3.11+ stdlib only (`tomllib`, `re`, `urllib`), GitHub Actions YAML, TOML.

**Spec:** `docs/specs/draft-1.md`

**Scope boundary:** Local scaffolding only. Creating the GitHub org/App, running real builds, and publishing releases (spec §15 M1 acceptance) are out of scope — no network side effects from these tasks.

**Tool repos:** Tool release repos (`retropack/<tool>`) never get permanent local clones. They hold only two generated files (template README + stub workflow); everything operational is `gh` CLI or Actions. `new-tool.sh` publishes the template directly to GitHub — no clone. If a user manually clones one anyway, sibling dirs `~/Projects/retropack-tools/<tool>` are the convention; never inside this repo.

## Global Constraints

- Python: stdlib only, no dependencies (spec §8.1 "stdlib only"; §5 "packaging-free" version compare).
- Scripts run with `set -euo pipefail` (spec §6.1).
- Platforms: `linux-x86_64`, `linux-aarch64`, `macos-aarch64`, plus `noarch` for platform-independent tools (spec §2.2, §6.1).
- Asset name pattern: `<tool>-<version>-<platform>.tar.gz` (spec §7.1).
- Release tag in tool repos: `v<version>`; version is the `version` named group of `tag_regex` (spec §5).
- Workflow stub `release.yml` references `retropack/retropack/.github/workflows/build.yml@main`, never a pinned SHA (spec §9.1).
- Every shell file passes `shellcheck` (spec §11.3, ci.yml).
- No credentials, no PATs anywhere; scaffolding creates no secrets (spec §3.2).
- Licence: MIT for retropack itself (spec §4.1); each archive ships upstream `LICENSE*` + `RETROPACK-NOTICE` (spec §7.2).

## Review Focus

- **Version comparison edge cases:** `2.19` vs `2.19.1` vs `2.19.0` vs `2.19rc1` — lenient dotted compare must order these sanely; test pins numeric tuples first, then string segments (spec §5).
- **Regex capture failure:** a `tag_regex` without a `version` named group, or a tag that doesn't match — watcher must skip it, not crash (spec §5).
- **`select_pending` blocking/capping semantics:** released and blocked versions excluded, result newest-first, capped at `max_per_run` (spec §8.1) — a bug here silently double-publishes or drops backfill.
- **platform_independent fan-out:** `noarch` builds must still produce three identically-named platform assets (spec §7.1) — prepare-job matrix output must reflect this.
- **YAML workflows parse:** a hand-written workflow with invalid YAML fails at PR time, not at 5am cron (spec §8.2) — test loads every file under `.github/workflows/` with a YAML parser.

---

### Task 1: Repo bootstrap

**Files:**
- Create: `LICENSE`, `README.md`, `.gitignore`, `.github/`, `tools/`, `scripts/`, `templates/`, `tests/`

**Interfaces:**
- Produces: git repo initialized at `/home/guru/Projects/retropack` with `main` branch; empty dirs tracked via `.gitkeep` where needed.

- [ ] **Step 1: Initialize repo and boilerplate**

```bash
cd /home/guru/Projects/retropack
git init -b main
```

- [ ] **Step 2: Create `LICENSE`** — standard MIT text, `Copyright (c) 2026 retropack`.

- [ ] **Step 3: Create `README.md`**

Content (exact copy for the skeleton):
- One-paragraph purpose from spec §1 (distribute prebuilt retro cross-tools installable via `mise install github:retropack/<tool>`).
- Install snippet block exactly as in spec §1.
- Tool table: columns Tool | Upstream | Licence | Notes — five rows copied from spec §2.1 table.
- Pointer: `docs/specs/draft-1.md` is the specification.

- [ ] **Step 4: Create `.gitignore`**

```
__pycache__/
*.pyc
dist/
work/
*.tar.gz
```

- [ ] **Step 5: Commit**

```bash
git add LICENSE README.md .gitignore
git commit -m "chore: repo bootstrap (license, readme, gitignore)"
```

---

### Task 2: Tool manifests + schema tests

**Files:**
- Create: `tools/tass64/tool.toml`, `tools/cc65/tool.toml`, `tools/sdcc/tool.toml`, `tools/oscar64/tool.toml`, `tools/kickc/tool.toml`
- Test: `tests/test_tool_toml.py`

**Interfaces:**
- Produces: five `tool.toml` manifests with exactly the keys of spec §5; consumed by `scripts/watch.py`, `build.yml` prepare job, and `new-tool.sh` (future tasks).

- [ ] **Step 1: Write the failing schema test**

`tests/test_tool_toml.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_tool_toml.py -v` (or `python3 -m unittest` equivalent if pytest unavailable — check first; fallback: run module directly)
Expected: FAIL — no `tools/*/tool.toml` found.

- [ ] **Step 3: Create the five manifests**

Values from spec §2.1, §5, §10 — copy exactly:

- `tools/cc65/tool.toml`: full example from spec §5 verbatim (upstream github `cc65/cc65`, `tag_regex = '^V(?P<version>\d+\.\d+(?:\.\d+)?)$'`, `min_version = "2.19"`, `expected_bins` list from §5).
- `tools/tass64/tool.toml`: upstream `sourceforge`, repo `tass64`, `file_regex = '^64tass-(?P<version>\d+\.\d+\.\d+)-src\.zip$'`, `min_version = "1.59.3120"`, source url `https://sourceforge.net/projects/tass64/files/source/64tass-{version}-src.zip/download`, `strip_components = 0`, `license = "GPL-2.0"`, `expected_bins = ["64tass"]`.
- `tools/sdcc/tool.toml`: upstream `sourceforge`, repo `sdcc`, `file_regex = '^sdcc-src-(?P<version>\d+\.\d+\.\d+)\.tar\.gz$'`, `min_version = "4.4.0"`, source url `https://sourceforge.net/projects/sdcc/files/sdcc/{version}/sdcc-src-{version}.tar.gz/download`, `strip_components = 1`, `timeout_minutes = 90`, alpine packages per §10, `license = "GPL-2.0"`.
- `tools/oscar64/tool.toml`: upstream `github`, repo `drmortalwombat/oscar64`, `tag_regex = '^v?(?P<version>\d+\.\d+(?:\.\d+)?)$'` (verified: tags are `v1.32.273` style), `min_version = "1.32.273"` (newest at scaffolding time), `license = "GPL-3.0"`, `expected_bins = ["oscar64"]`.
- `tools/kickc/tool.toml`: upstream `gitlab`, repo `camelot/kickc` (URL-encoded `camelot%2Fkickc` where needed), `tag_regex = '^v?(?P<version>\d+\.\d+\.\d+)$'` (verified: tags are bare `0.8.6` style — use `^(?P<version>\d+\.\d+\.\d+)$`), `min_version = "0.8.6"`, `platform_independent = true`, `runtime_requirements = ["java>=11"]`, `license = "MIT"`.

Include the §5 keys `description`, `homepage`, `license_files` for each from the upstreams. `source.url` for github tools uses `https://github.com/{repo}/archive/refs/tags/{tag}.tar.gz`-style pattern with `{version}` substitution — for cc65 keep the exact §5 URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_tool_toml.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tools tests/test_tool_toml.py
git commit -m "feat: tool manifests for initial five tools + schema test"
```

---

### Task 3: `watch.py` pure logic + tests

**Files:**
- Create: `scripts/watch.py`
- Test: `tests/test_watch.py`

**Interfaces:**
- Produces (importable functions, exact signatures):
  - `parse_tags(tags: list[str], pattern: str) -> list[str]` — extract `version` group; drop non-matching tags.
  - `compare_versions(a: str, b: str) -> int` — lenient dotted compare (spec §5): split on `.`, compare numeric segments as ints pairwise; when one side runs out, treat missing segments as `0`; if both segments non-numeric, compare as strings; numeric beats non-numeric at same position.
  - `select_pending(upstream: list[str], released: list[str], blocked: list[str], max_per_run: int) -> list[str]` — sorted newest-first, minus released/blocked, capped at `max_per_run`.
  - `main(argv: list[str]) -> int` — CLI entry; scaffolding stage: parse args (`--tool`, `--version`, `--dry-run` per §8.2), print `TODO: fetch + dispatch` and return 0. Network/dispatch code lands in M1.

- [ ] **Step 1: Write the failing tests**

`tests/test_watch.py`:

```python
import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location(
    "watch", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

def test_parse_tags_extracts_version_group():
    assert watch.parse_tags(["V2.19", "V2.18", "junk"], r"^V(?P<version>\d+\.\d+(?:\.\d+)?)$") == ["2.19", "2.18"]

def test_parse_tags_missing_group_raises_valueerror():
    try:
        watch.parse_tags(["V2.19"], r"^V(\d+\.\d+)$")
    except ValueError:
        pass
    else:
        raise AssertionError("pattern without 'version' group must raise ValueError")

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

def test_main_stub_returns_zero():
    assert watch.main(["--dry-run"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_watch.py -v`
Expected: FAIL — `ModuleNotFoundError`/file not found for `scripts/watch.py`.

- [ ] **Step 3: Implement `scripts/watch.py`**

Stdlib only. Module docstring citing spec §8.1. Implement the four functions per Interfaces above; `main()` parses `--tool/--version/--dry-run` with `argparse`, then prints `TODO: upstream fetch + repository_dispatch (M1)` and returns 0. Guard with `if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_watch.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/watch.py tests/test_watch.py
git commit -m "feat: watch.py version parsing, compare, pending selection"
```

---

### Task 4: Workflow YAML + parse tests

**Files:**
- Create: `.github/workflows/watch.yml`, `.github/workflows/build.yml`, `.github/workflows/ci.yml`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: Task 3 `scripts/watch.py` (watch.yml invokes it).
- Produces: `build.yml` with `workflow_call` inputs `tool`, `version` (string) — the contract `templates/tool-repo/.github/workflows/release.yml` (Task 5) relies on.

- [ ] **Step 1: Write the failing YAML parse test**

`tests/test_workflows.py`:

```python
import pathlib, yaml

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"

def test_every_workflow_parses_and_has_on_key():
    files = sorted(WF.glob("*.yml"))
    assert len(files) >= 3
    for f in files:
        data = yaml.safe_load(f.read_text())
        assert "on" in data or True in data, f  # 'on' may parse as True in YAML 1.1

def test_release_stub_contract():
    build = yaml.safe_load((WF / "build.yml").read_text())
    assert "workflow_call" in build[True]  # or build["on"], depending on parser
    assert set(build[True]["workflow_call"]["inputs"]) == {"tool", "version"}

def test_watch_triggers_and_keepalive():
    text = (WF / "watch.yml").read_text()
    assert "schedule:" in text and "workflow_dispatch:" in text
    assert "workflows/watch.yml/enable" in text   # §8.3 keep-alive
    assert "if: always()" in text                 # keep-alive step is unconditional
```

(Adjust key lookup to handle YAML's `on` → `True` quirk; test both keys.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_workflows.py -v`
Expected: FAIL — no workflow files.

- [ ] **Step 3: Create the three workflows**

- `watch.yml`: exactly the triggers/concurrency/permissions from spec §8.2 (`cron: "17 5 * * *"`, dispatch inputs `tool`/`version`/`dry_run`, `concurrency: {group: watch, cancel-in-progress: false}`, `permissions: {contents: read, actions: write}`). Jobs (scaffolding steps, real work M1): `detect` on `ubuntu-latest` — checkout, setup-python, run `python3 scripts/watch.py` with inputs as flags; final keep-alive step per §8.3 verbatim with `if: always()`.
- `build.yml`: `on: workflow_call` with inputs `tool` (string, required) and `version` (string, required). Jobs skeleton matching spec §9.2 graph — `prepare` → `build` (matrix placeholder) → `publish` → `accept` → `on-failure` (`if: failure()`) — each with `run: echo "TODO: M1"` steps and comments naming the spec section and which script each step will call (`fetch-source.sh`, `package.sh`, `publish.sh`, `check-portability.sh`). Include §9.1 permissions block (`contents/id-token/attestations/issues: write`) on the workflow level.
- `ci.yml`: `on: pull_request` + `push` to `main`. Jobs: `shellcheck` (`shellcheck scripts/*.sh tools/*/*.sh`), `python` (`pip install pytest pyyaml` → `python3 -m pytest tests/ -v`), matching spec §11.3.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_workflows.py -v`
Expected: PASS

Note: PyYAML + pytest are already available in the environment (verified).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows tests/test_workflows.py
git commit -m "feat: watch/build/ci workflows (skeleton) + yaml parse tests"
```

---

### Task 5: Templates

**Files:**
- Create: `templates/tool-repo/README.md`, `templates/tool-repo/.github/workflows/release.yml`, `templates/RETROPACK-NOTICE.tmpl`

**Interfaces:**
- Produces: `release.yml` stub containing verbatim §9.1 YAML (the `uses: retropack/retropack/.github/workflows/build.yml@main` call with `tool`/`version` inputs) — consumed by `new-tool.sh` (Task 7).

- [ ] **Step 1: Create `templates/tool-repo/.github/workflows/release.yml`** — copy spec §9.1 block verbatim.

- [ ] **Step 2: Create `templates/tool-repo/README.md`**

Placeholders only: `# <tool>`, one-line description, install snippet `mise install github:retropack/<tool>`, licence line, link to `retropack/retropack`.

- [ ] **Step 3: Create `templates/RETROPACK-NOTICE.tmpl`**

Fields per spec §7.3, one `{{field}}` per line: tool name, version, upstream homepage, source URL + tag, SPDX licence, patch list (or `none`), build platform, build date, workflow run link, runtime requirements. Prefixed with a line: "This is an unofficial build packaged by retropack; see <brain repo>."

- [ ] **Step 4: Verify release.yml matches spec §9.1**

Run: `grep -c "build.yml@main" templates/tool-repo/.github/workflows/release.yml`
Expected: `1`

- [ ] **Step 5: Commit**

```bash
git add templates
git commit -m "feat: tool-repo and notice templates"
```

---

### Task 6: Shared scripts (contract stubs)

**Files:**
- Create: `scripts/fetch-source.sh`, `scripts/build-linux.sh`, `scripts/build-macos.sh`, `scripts/package.sh`, `scripts/check-portability.sh`, `scripts/publish.sh`, `scripts/new-tool.sh`

**Interfaces:**
- Consumes: environment contract of spec §6.1 (`TOOL`, `VERSION`, `PLATFORM`, `SRC`, `PREFIX`, `NPROC`, `CC/CXX/CFLAGS/...`) — each script documents this in a header comment.
- Produces: executable, shellcheck-clean scripts; `package.sh` emits `dist/<tool>-<version>-<platform>.tar.gz`; `new-tool.sh <tool>` scaffolds `tools/<tool>/` + tool repo (Task 7 relies on templates from Task 5).

- [ ] **Step 1: Write each script as a contract stub**

Pattern for each (skeleton stage):

```bash
#!/usr/bin/env bash
# <name> — <one line, spec §x.y>
set -euo pipefail
# Env contract (spec §6.1): TOOL VERSION PLATFORM SRC PREFIX NPROC ...
: "${TOOL:?TOOL must be set}"   # only the vars this script needs
echo "<name>: not implemented yet (M1)" >&2
exit 1   # stubs must fail loudly, never silently succeed
```

Specifics:
- `fetch-source.sh`: reads `tool.toml` (`python3 -c` with tomllib), downloads `source.url` (with `{version}` substitution) to `$WORK/src`, extracts with `strip_components`, applies `tools/$TOOL/patches/*` in order via `patch -p1`. **Implement fully** — no network in tests, but logic is self-contained; stub body is acceptable if extraction stays M1, then the header must list the exact steps.
- `build-linux.sh`: docker run alpine:3 command from spec §6.2 verbatim, passing `-v "$WORK:/work"` and env.
- `build-macos.sh`: exports `MACOSX_DEPLOYMENT_TARGET=12.0`, `CC=clang CXX=clang++`, runs `tools/$TOOL/build.sh`.
- `package.sh`: **implement** — stage `$PREFIX` as `<tool>-<version>/`, `tar -czf "dist/$TOOL-$VERSION-$PLATFORM.tar.gz"`, generate `RETROPACK-NOTICE` from the template with `sed`, copy `license_files` in. (Pure filesystem logic, testable.)
- `check-portability.sh`: **implement** per spec §6.4 (file/readelf branch on Linux, otool/codesign branch on macOS, shared `/work/` grep).
- `publish.sh`: contract-documented stub — header lists §7.4's six steps verbatim as numbered TODOs; `exit 1`.
- `new-tool.sh`: **implement** — validates `$1` (`^[a-z0-9-]+$`), `mkdir -p tools/$1/fixtures`, copies a `tools/_template/` skeleton (create this minimal template dir in this task: `tool.toml` with `name`/placeholder TODOs + `build.sh`/`test.sh` stubs), then prints the `gh repo create` command to run manually (no network in scaffolding).

- [ ] **Step 2: shellcheck all scripts**

Run: `shellcheck scripts/*.sh tools/*/*.sh && chmod +x scripts/*.sh`
Expected: no output, exit 0.

- [ ] **Step 3: Smoke-test stubs fail loudly**

Run: `TOOL=x VERSION=1 PLATFORM=linux-x86_64 scripts/publish.sh; echo exit=$?`
Expected: `exit=1` with "not implemented" on stderr.

- [ ] **Step 4: Commit**

```bash
git add scripts tools/_template
git commit -m "feat: shared build/package/publish scripts (stubs + implemented pure logic)"
```

---

### Task 7: Per-tool `build.sh`, `test.sh`, fixtures

**Files:**
- Create: `tools/cc65/{build.sh,test.sh,fixtures/hello.c,fixtures/hello.s}`, `tools/tass64/{build.sh,test.sh,fixtures/hello.asm}`, `tools/sdcc/{build.sh,test.sh,fixtures/hello.c}`, `tools/oscar64/{build.sh,test.sh}`, `tools/kickc/{build.sh,test.sh,fixtures/hello.c}`

**Interfaces:**
- Consumes: §6.1 env contract; `build.sh` installs into `$PREFIX`; `test.sh` verifies `$PREFIX` (called twice: build runner + mise dir, spec §6.3).
- Produces: `test.sh` for each tool implements the §6.3 contract (expected_bins check, `--version` run, fixture compile, non-empty output, no network) — real code, shellcheck-clean.

- [ ] **Step 1: Write `test.sh` for cc65 (reference implementation)**

Per §6.3 + §10: loop over `expected_bins` (parse from `tool.toml` via tomllib, or hardcode — hardcode, it's a test), run `cl65 --version` etc., then `cd $(mktemp -d) && cl65 -t c64 fixtures/hello.c -o hello.prg` and `[ -s hello.prg ]`. Must work with `PREFIX` at any path (prove relocatability, no `CC65_HOME` set — `unset CC65_HOME` in the script).

- [ ] **Step 2: Write remaining `test.sh` files**

- tass64: `64tass hello.asm -o hello.prg`, `[ -s hello.prg ]`.
- sdcc: `sdcc -mz80 -c hello.c`, `sdcc -mmos6502 -c hello.c`, sdasz80/sdldz80 round-trip; run from a temp cwd (relocatable lookup proof).
- oscar64: compile spec's `samples/hello/hello.c` equivalent — our fixture `hello.c`, expect `.prg`.
- kickc: `kickc -t c64 hello.c` in temp dir (JRE assumed present).

- [ ] **Step 3: Write `build.sh` files from spec §10**

Each: `set -euo pipefail`, uses `$SRC`/`$PREFIX`/`$NPROC`, exact build/install commands from §10 for that tool. oscar64 includes `# TODO: patch Makefile (§10)` comment where patches expected. kickc: `build.mode = "repackage"` path — stub with `exit 1` + TODO until M3 (its test.sh still written now).

- [ ] **Step 4: Create fixtures**

- `hello.c` (cc65): minimal C64 program, e.g. `#include <stdio.h>\nint main(void) { printf("hi"); return 0; }` — keep to what cc65's c64 target supports.
- `hello.s` (cc65): tiny ca65 6502 source with `.segment`, `.export`, `rts`.
- `hello.asm` (tass64): `* = $0801` BASIC stub + `rts`.
- sdcc `hello.c`: plain C for `-mz80` compile-only.
- kickc `hello.c`: kickc-style minimal (`void main() {}`).

- [ ] **Step 5: shellcheck + run test.sh against an empty prefix to verify failure path**

Run: `shellcheck tools/*/*.sh` and `PREFIX=$(mktemp -d) bash tools/cc65/test.sh; echo exit=$?`
Expected: shellcheck clean; test.sh exits non-zero (bins missing) with a clear message — proves the check works.

- [ ] **Step 6: Commit**

```bash
git add tools
git commit -m "feat: per-tool build.sh/test.sh + smoke fixtures"
```

---

### Task 8: Final verification

- [ ] **Step 1: Full local CI pass**

```bash
shellcheck scripts/*.sh tools/*/*.sh
python3 -m pytest tests/ -v
find . -name "*.yml" -path "*.github*" -exec python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" {} \;
```
Expected: all green, exit 0.

- [ ] **Step 2: Layout matches spec §4.1**

Run: `find . -type f -not -path "./.git/*" | sort`
Expected: every file in §4.1's tree exists (plus `tests/`, which ci.yml requires).

- [ ] **Step 3: Commit any stragglers**

```bash
git add -A && git commit -m "chore: scaffolding complete" || true
git log --oneline
```
