# retropack — Implementation Specification

Status: draft v1 · Scope: GitHub-only implementation (one brain repo, one release repo per tool)

* * *

## 1. Purpose

`retropack` distributes prebuilt, redistributable cross-development tools for retro targets (6502 first, Z80 later) so they can be installed individually with [mise](https://mise.jdx.dev) via its built-in `github:` backend:

```toml
[tools]
"github:retropack/cc65"   = "2.19"
"github:retropack/tass64" = "latest"
```

### 1.1 Goals

*   G1 One-line install of each tool on linux/x86_64, linux/aarch64, macos/aarch64 with no compiler, Java, or other toolchain on the user's machine (exception: JVM tools need a JRE on PATH).
    
*   G2 Fully automated tracking of upstream releases: detection, build, test, publish — with no human in the loop.
    
*   G3 Minimal recurring maintenance: no expiring credentials, no dependency-bump PRs, no cron that silently dies. Manual attention is needed only when a build actually breaks, and the system tells you.
    
*   G4 Verifiable supply chain: checksums + GitHub artifact attestations on every asset; mise verifies them automatically.
    
*   G5 Adding a tool is a scripted, sub-hour job.
    

### 1.2 Non-goals (v1)

*   Windows or linux/x86 (32-bit) builds.
    
*   Git snapshot / nightly builds of upstreams (see §14 Future work).
    
*   Inclusion in the official mise registry / packslip manifests (§14).
    
*   Any tool whose licence forbids redistribution of binaries or repackaged artifacts. KickAssembler is excluded for this reason.
    

* * *

## 2. Scope

### 2.1 Initial tool set

| Tool | Upstream | Licence | Language | Platform-specific binary | Notes |
| --- | --- | --- | --- | --- | --- |
| `tass64` | SourceForge `tass64` (svn) | GPL-2.0 | C | yes | Binary is `64tass` |
| `cc65` | GitHub `cc65/cc65` | Zlib | C | yes | Needs `lib/ include/ asminc/ cfg/ target/` beside `bin/` |
| `sdcc` | SourceForge `sdcc` (svn) | GPL-2.0 | C++ | yes | Heaviest build; 6502/Z80 ports only; exclude non-free libs |
| `oscar64` | GitHub `drmortalwombat/oscar64` | GPL-3.0 | C++ | yes | Needs `include/` beside `bin/` |
| `kickc` | GitLab `camelot/kickc` | MIT | Java | **no** (JVM) | Needs JRE ≥ 11 on user PATH |

Licence policy: a tool is admitted only if its licence permits redistribution of the binaries/artifacts we produce. Every release archive ships the upstream `LICENSE` file(s) plus a `RETROPACK-NOTICE` file (see §7.3). Source tarballs are not mirrored; the notice links to the exact upstream source tag (sufficient for the GPL tools since we distribute unmodified sources' builds and link to source; if we ever patch, the patch is in the brain repo and referenced in the notice).

### 2.2 Platforms

| Platform id | GitHub runner | Build method |
| --- | --- | --- |
| `linux-x86_64` | `ubuntu-latest` | Static musl build inside `alpine:3` container via `docker run` |
| `linux-aarch64` | `ubuntu-24.04-arm` | Static musl build inside `alpine:3` container via `docker run` |
| `macos-aarch64` | `macos-latest` (Apple Silicon) | Native clang, `MACOSX_DEPLOYMENT_TARGET=12.0`, no Homebrew runtime deps |

Platform-independent tools (JVM) build once on `ubuntu-latest` and publish the identical archive under all three platform asset names (§7.1).

* * *

## 3. Architecture

```
                 ┌──────────────────────────────────────────────┐
                 │  retropack/retropack  (brain, public)          │
                 │  - tools/<name>/tool.toml, build.sh, test.sh │
                 │  - scripts/watch.py, scripts/*.sh            │
  cron / manual ─┼─▶ .github/workflows/watch.yml               │
                 │     detect missing (tool, version) pairs     │
                 │     repository_dispatch(build) via App token │
                 │  - .github/workflows/build.yml (reusable)    │
                 └───────────────┬──────────────────────────────┘
                                 │ repository_dispatch  (GitHub App token)
                                 ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  retropack/<tool>  (release repo, public, one per tool)        │
   │  - README.md, .github/workflows/release.yml (15-line stub)    │
   │  - stub `uses: retropack/retropack/.github/workflows/build.yml` │
   │  - builds on 3 runners → test → attest → GitHub Release       │
   │  - opens issue `build-failure` on failure                     │
   └──────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
                    users: mise install github:retropack/<tool>
```

### 3.1 Why this split

*   **Brain repo holds all logic** (one place to edit, one cron).
    
*   **Tool repos own their releases, runs, and attestations.** Attestations and provenance are then queryable for `retropack/<tool>` — exactly what mise checks for `github:retropack/<tool>`. Release creation uses the tool repo's own `GITHUB_TOKEN` (no cross-repo write token needed for publishing).
    
*   **Tool repo workflows are triggered only by** `repository_dispatch` **/** `workflow_dispatch`, which are exempt from GitHub's 60-day inactivity rule. Only the brain has a `schedule:` trigger, and it is protected (§8.3).
    
*   **State = the tool repo's published releases.** The brain writes nothing back; the watcher is idempotent and self-healing by construction (§8.1).
    

### 3.2 GitHub App (the only credential)

Create an org-owned GitHub App `retropack-bot`:

*   Permissions: Repository → Contents: **Read & write** (required for `repository_dispatch`), Metadata: read, Issues: read.
    
*   Installed on the org with **All repositories** (so new tool repos need no extra step).
    
*   Store in `retropack/retropack`: variable `RETROPACK_APP_ID`, secret `RETROPACK_APP_PRIVATE_KEY`.
    
*   Tokens are minted per run with `actions/create-github-app-token@v2`, scoped to the tool repos being dispatched. **Nothing expires.**
    

No PATs anywhere.

* * *

## 4. Repository layouts

### 4.1 `retropack/retropack` (brain)

```
.
├── README.md                     # project overview, user-facing install snippets, tool table
├── LICENSE                       # MIT for the retropack scripts themselves
├── tools/
│   └── <tool>/
│       ├── tool.toml             # manifest (§5)
│       ├── build.sh              # build one platform (§6.2)
│       ├── test.sh               # smoke test an installed prefix (§6.3)
│       └── patches/              # optional, applied with `patch -p1` in order
├── scripts/
│   ├── watch.py                  # upstream/released diff + dispatch (stdlib only)
│   ├── build-linux.sh            # host-side wrapper: docker run alpine → build.sh
│   ├── build-macos.sh            # host-side wrapper for macOS
│   ├── fetch-source.sh           # download+verify+extract source per tool.toml
│   ├── package.sh                # produce <tool>-<version>-<platform>.tar.gz + NOTICE
│   ├── check-portability.sh      # static-ness / dylib checks (§6.4)
│   ├── publish.sh                # idempotent draft→assets→undraft release (§7.4)
│   └── new-tool.sh               # scaffold tool repo + tools/<tool>/ (§11)
├── templates/
│   ├── tool-repo/                # contents of a fresh tool repo (README, stub workflow)
│   └── RETROPACK-NOTICE.tmpl
└── .github/workflows/
    ├── watch.yml                 # schedule + workflow_dispatch (§8)
    ├── build.yml                 # reusable (workflow_call) (§9)
    └── ci.yml                    # PR checks: shellcheck, python tests, tool.toml schema
```

### 4.2 `retropack/<tool>` (release repo)

```
.
├── README.md                     # generated from template: what it is, install snippet, licence, link to brain
└── .github/workflows/release.yml # stub, identical for every tool (§9.1)
```

No other content. The default branch `main` exists only so releases have a target commit.

* * *

## 5. Tool manifest — `tools/<tool>/tool.toml`

```toml
[tool]
name         = "cc65"
description  = "C compiler and assembler suite for 6502 systems"
homepage     = "https://cc65.github.io"
license      = "Zlib"                 # SPDX id
license_files = ["LICENSE"]           # paths in source tree, copied into archive
platform_independent = false          # true → build once, publish under all platform names
runtime_requirements = []             # e.g. ["java>=11"] — documented in README + NOTICE

[upstream]
type        = "github"                # github | gitlab | sourceforge
repo        = "cc65/cc65"             # github/gitlab: owner/repo (gitlab: URL-encoded path ok)
                                      # sourceforge: project unix name
tag_regex   = '^V(?P<version>\d+\.\d+(?:\.\d+)?)$'   # named group "version" → normalized version
# sourceforge only: regex applied to release filenames from best_release.json / RSS
# file_regex = '^sdcc-src-(?P<version>\d+\.\d+\.\d+)\.tar\.gz$'
min_version = "2.19"                  # ignore anything older (bounds backfill)
skip_versions = []                    # explicit exclusions (broken upstream tags)
max_per_run = 2                       # cap on dispatches per watch run for this tool

[source]
url = "https://github.com/cc65/cc65/archive/refs/tags/V{version}.tar.gz"
strip_components = 1
# optional: sha256 lookup is not possible for upstream-generated tarballs; integrity
# comes from HTTPS + the fact that the build is reproducible from the tag.

[build]
mode = "source"                       # source | repackage
alpine_packages = ["build-base"]      # apk add … inside container
macos_packages  = []                  # brew install … (build-time only; must not leak into runtime deps)
timeout_minutes = 30

[test]
# test.sh is always run; this section is for declarative extras
expected_bins = ["cc65", "ca65", "ld65", "cl65", "ar65", "co65", "da65", "od65", "sp65", "grc65", "sim65"]
```

Version normalization rule: the `version` named group is the canonical version string. Release tag in the tool repo is `v<version>`; mise strips the `v` automatically. Versions are compared with a lenient numeric-dotted comparison (Python `packaging`-free implementation in `watch.py`: split on `.`, compare integer tuples, non-numeric segments compare as strings after numeric ones).

* * *

## 6. Build contract

### 6.1 Environment given to `build.sh`

| Var | Meaning |
| --- | --- |
| `TOOL` | tool name |
| `VERSION` | normalized version |
| `PLATFORM` | `linux-x86_64` | `linux-aarch64` | `macos-aarch64` | `noarch` |
| `OS`, `ARCH` | split of PLATFORM |
| `SRC` | extracted source tree (already patched) |
| `PREFIX` | absolute path to `<work>/<tool>-<version>/` — build.sh must install into this |
| `NPROC` | parallelism |
| `CC`, `CXX`, `CFLAGS`, `CXXFLAGS`, `LDFLAGS` | preset per platform (see 6.2); build.sh may append, not replace, unless it has a documented reason |

`build.sh` must be idempotent-ish and must exit non-zero on failure. It runs with `set -euo pipefail`.

### 6.2 Platform presets

**Linux (both arches)** — executed _inside_ `alpine:3` via `scripts/build-linux.sh`:

```
docker run --rm -v "$WORK:/work" -w /work -e … alpine:3 sh -c '
  apk add --no-cache $ALPINE_PACKAGES && sh /work/brain/tools/$TOOL/build.sh'
```

Presets: `CC=gcc CXX=g++ CFLAGS="-O2" LDFLAGS="-static"`. Result must be a fully static ELF (musl). Rationale: runs on any glibc or musl distro, no libc version issues; the `docker run` approach (rather than `container:`) avoids Node/glibc incompatibilities of JS actions inside Alpine. Docker is preinstalled on both `ubuntu-latest` and `ubuntu-24.04-arm`.
**macOS** — executed directly on the runner via `scripts/build-macos.sh`:
Presets: `CC=clang CXX=clang++ MACOSX_DEPLOYMENT_TARGET=12.0 CFLAGS="-O2"`. Build-time Homebrew packages (e.g. `bison`, `boost`) are allowed, but the resulting binaries must not link any `/opt/homebrew` dylib (checked in 6.4). Binaries are ad-hoc signed by the linker on arm64; `codesign --verify` is run as a sanity check.
**noarch** (platform_independent = true) — executed on `ubuntu-latest` directly (no container); e.g. `apt-get install maven` or plain repackaging.

### 6.3 `test.sh` contract

Invoked twice with `PREFIX` pointing at (a) the freshly built prefix on the build runner, and (b) the mise-installed directory during acceptance (`mise where github:retropack/<tool>@<version>`). It must:

*   Verify every `expected_bins` exists and is executable.
    
*   Run each tool's `--version`/`-V` equivalent.
    
*   Perform a real end-to-end compile/assemble of a tiny fixture in `tools/<tool>/fixtures/` and check the output file exists and is non-empty (e.g. `cl65 -t c64 hello.c -o hello.prg`; `64tass hello.asm -o hello.prg`; `sdcc -mz80 -c hello.c`; `oscar64 hello.c`; `kickc hello.c`).
    
*   Must not require network.
    

### 6.4 Portability checks (`check-portability.sh`)

*   Linux: every ELF under `bin/` reports `statically linked` (`file`), and `readelf -d` shows no `NEEDED`.
    
*   macOS: `otool -L` lists only `/usr/lib/*` and `/System/*`; `codesign --verify --strict` succeeds; `MACOSX_DEPLOYMENT_TARGET` visible via `otool -l | grep minos`.
    
*   All: no absolute build paths embedded in text config files under the prefix (grep for `/work/`).
    

* * *

## 7. Release artifact specification

### 7.1 Asset naming

```
<tool>-<version>-linux-x86_64.tar.gz
<tool>-<version>-linux-aarch64.tar.gz
<tool>-<version>-macos-aarch64.tar.gz
SHA256SUMS
```

*   No libc tag in the name (binaries are static; keeps mise autodetection unambiguous).
    
*   Platform-independent tools publish the **same bytes** under all three platform names, so mise autodetection always finds a match. (A single `-noarch` asset is not used: autodetection behaviour for names without OS/arch tokens is not guaranteed.)
    
*   `SHA256SUMS` (aggregate, for humans and `sha256sum -c`) ships with every release. Per-asset `.sha256` files were **dropped after M1**: mise's github backend verifies downloads via the **GitHub API asset digest** (`using GitHub API digest for checksum verification` in `MISE_LOG_LEVEL=debug mise install`) — it reads neither checksum file (resolved §13 item).
    

### 7.2 Archive layout

```
<tool>-<version>/
├── bin/                # all executables; wrapper scripts for JVM tools
├── lib/ include/ …     # whatever the tool needs, in the layout it expects relative to bin/
├── LICENSE*            # upstream licence file(s)
└── RETROPACK-NOTICE     # see 7.3
```

Exactly one top-level directory → mise auto-applies `strip_components=1` and finds `bin/`. Users need no `bin_path`/`strip_components` options. Everything inside must be relocatable (no absolute paths): cc65 and oscar64 look up support dirs relative to the executable; sdcc is configured with relocatable prefix lookup and verified by `test.sh` from an arbitrary path.
JVM tools: `bin/<tool>` is a POSIX sh wrapper resolving its own location and calling `exec java $JAVA_OPTS -jar "$HERE/../lib/<tool>.jar" "$@"`. It prints a clear error if `java` is not found.

### 7.3 `RETROPACK-NOTICE`

Generated from template; contains: tool name/version, upstream homepage, exact source URL/tag used, licence SPDX id, list of applied patches (if any) with link to brain repo commit, build platform and date, link to the workflow run, and runtime requirements.

### 7.4 Publishing (idempotent, atomic)

1.  If a **published** (non-draft) release `v<version>` exists → exit 0 (`already released`).
    
2.  If a **draft** release `v<version>` exists → delete it (leftover of a failed run).
    
3.  Create release `v<version>` as **draft** targeting `main`, generated notes disabled, body from template (upstream link, install snippet, checksums).
    
4.  Upload all assets + `SHA256SUMS`.
    
5.  Run `actions/attest-build-provenance` on all archives (`subject-path: dist/*.tar.gz`).
    
6.  Flip draft → published. Pass `--latest` only if `<version>` is the highest published version in the repo (backfilling older versions must not steal "latest").
    

mise ignores drafts, so users can never observe a half-uploaded release.

* * *

## 8. Watcher — `watch.yml` + `scripts/watch.py`

### 8.1 Algorithm (per tool, all tools in one run)

```
upstream  = versions from upstream API matching tag_regex/file_regex, >= min_version, not in skip_versions
released  = tags of published (non-draft, non-prerelease) releases in retropack/<tool>, stripped of 'v'
blocked   = versions named in OPEN issues labelled `build-failure` in retropack/<tool>
            (title format: "build failure: <tool> <version>")
pending   = sorted(upstream − released − blocked)[-max_per_run:]     # newest first, capped
for v in pending: repository_dispatch(retropack/<tool>, event_type="build", client_payload={version: v})
```

Properties: idempotent; automatic backfill of the whole `>= min_version` history; automatic daily retry of failures; **self-throttling** — a failure opens an issue, which blocks that version until a human closes the issue (closing = "retry"). No write-back to the brain repo needed.
Upstream adapters (all JSON APIs, no HTML scraping):
| type | Endpoint |
| --- | --- |
| `github` | `GET /repos/{repo}/releases?per_page=100` (fallback `/tags` if `use_tags = true`), exclude drafts/prereleases |
| `gitlab` | `GET https://gitlab.com/api/v4/projects/{urlencoded}/releases` |
| `sourceforge` | `GET https://sourceforge.net/projects/{project}/best_release.json` and `GET https://sourceforge.net/projects/{project}/rss?path=/` (parse `<title>` file paths) — union, then `file_regex` |

Unauthenticated where possible; GitHub calls use the App token to avoid rate limits.

### 8.2 Triggers

```yaml
on:
  schedule: [{ cron: "17 5 * * *" }]     # daily, off the hour to avoid GitHub's busy minute
  workflow_dispatch:
    inputs:
      tool:    { description: "limit to one tool (optional)" }
      version: { description: "force a specific version (optional; bypasses released/blocked checks)" }
      dry_run: { type: boolean, default: false }
concurrency: { group: watch, cancel-in-progress: false }
permissions: { contents: read, actions: write }
```

### 8.3 Keep-alive (defence against the 60-day cron rule)

Last step of every `watch.yml` run, unconditional (`if: always()`):

```yaml
- run: gh api -X PUT "repos/${GITHUB_REPOSITORY}/actions/workflows/watch.yml/enable"
  env: { GH_TOKEN: "${{ github.token }}" }
```

Re-enabling resets GitHub's inactivity timer without a dummy commit. Requires `actions: write` (granted above). Additionally: GitHub emails the org owner when it disables a scheduled workflow; that email is the fallback signal. If it ever fires, the recovery is one click (Enable workflow) and this step then keeps it alive.

### 8.4 Notifications

*   Watch run failures (API outage, script bug) → GitHub's default "workflow failed" email. Nothing else is configured.
    
*   Build failures → issue in the tool repo (§9.3). Subscribe to the org's notifications or watch each tool repo.
    

* * *

## 9. Build & release — reusable `build.yml` + tool-repo stub

### 9.1 Tool repo stub `.github/workflows/release.yml` (identical for all tools)

```yaml
name: release
on:
  repository_dispatch:
    types: [build]
  workflow_dispatch:
    inputs:
      version: { required: true, description: "upstream version to build, e.g. 2.19" }
permissions:
  contents: write        # create release, tags
  id-token: write        # attestation signing
  attestations: write
  issues: write          # build-failure issues
concurrency:
  group: release-${{ inputs.version || github.event.client_payload.version }}
  cancel-in-progress: false
jobs:
  release:
    uses: retropack/retropack/.github/workflows/build.yml@main
    with:
      tool:    ${{ github.event.repository.name }}
      version: ${{ inputs.version || github.event.client_payload.version }}
```

Referencing `@main` (not a pinned SHA) is deliberate: fixes in the brain propagate to all tools with zero PRs. The brain's `ci.yml` protects `main`.

### 9.2 Reusable `build.yml` (in brain)

Inputs: `tool`, `version`. Jobs:

1.  `prepare` (ubuntu-latest): checkout `retropack/retropack`; parse `tools/<tool>/tool.toml` → job outputs (`platform_independent`, matrix JSON, timeouts). Check idempotency: if published release exists → set `skip=true` and all later jobs short-circuit successfully.
    
2.  `build` (matrix over platforms, or single `noarch` job): checkout brain; `fetch-source.sh` (download, apply `patches/`); `build-linux.sh` / `build-macos.sh` / direct; `test.sh` against `$PREFIX`; `check-portability.sh`; `package.sh` → `dist/<asset>`; upload as artifact `dist-<platform>`. `timeout-minutes` from manifest.
    
3.  `publish` (ubuntu-latest, needs build): download all artifacts; for `noarch` fan the single archive out to the three names; generate `SHA256SUMS`; `publish.sh` (§7.4) with `attest-build-provenance` between upload and undraft. Uses the tool repo's `GITHUB_TOKEN` (the run belongs to the tool repo).
    
4.  `accept` (matrix over the three runners, needs publish): install mise (`curl https://mise.run | sh`), `mise install "github:retropack/<tool>@<version>"` with `MISE_GITHUB_TOKEN=$GITHUB_TOKEN`, then run `tools/<tool>/test.sh` with `PREFIX=$(mise where github:retropack/<tool>@<version>)`. This proves: asset autodetection works on each platform, attestation verification passes, archive layout is right. Runs after publish because mise cannot install from a draft; a failure here opens an issue like any other failure (the release stays published — see 9.3).
    
5.  `on-failure` (`if: failure()`, needs all): create/refresh issue `build failure: <tool> <version>` with label `build-failure`, body containing run URL and failing job. If the failure is in `accept`, the issue title is `acceptance failure: <tool> <version>` (same label) so the watcher still blocks retries but a human knows the release exists and may need to be deleted.
    

### 9.3 Failure semantics

| Failure in | Result | Human action |
| --- | --- | --- |
| `build`/`test`/`portability` | No release created. Issue opened. Version blocked. | Fix `build.sh`/patches in brain, close issue → rebuilt next watch run (or `workflow_dispatch` immediately) |
| `publish` | Draft may remain; next run deletes it. Issue opened. | Usually transient; close issue |
| `accept` | Release is published but issue opened. | Investigate; if bad, delete release (`gh release delete`) and close issue → rebuild |

* * *

## 10. Per-tool build notes

### tass64

*   upstream: `sourceforge`, project `tass64`, `file_regex = '^64tass-(?P<version>\d+\.\d+\.\d+)-src\.zip$'`, `min_version = "1.59.3120"`.
    
*   source url: `https://sourceforge.net/projects/tass64/files/source/64tass-{version}-src.zip/download` (`strip_components = 0`; zip contains files at root — verify and adjust).
    
*   build: `make -j$NPROC CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"; install -Dm755 64tass $PREFIX/bin/64tass; install -Dm644 README $PREFIX/`.
    
*   alpine packages: `build-base`. macOS: none.
    
*   test: assemble fixture `hello.asm` for 6502.
    

### cc65

*   upstream: `github`, `cc65/cc65`, `tag_regex = '^V(?P<version>\d+\.\d+(?:\.\d+)?)$'`, `min_version = "2.19"`.
    
*   build: `make -j$NPROC PREFIX=/ CFLAGS=… LDFLAGS=…` then `make install PREFIX="$PREFIX" prefix="$PREFIX"` (cc65's Makefile uses `PREFIX`; ensure `datadir` resolves to `$PREFIX/share/cc65` **or** flatten to `$PREFIX/{lib,include,asminc,cfg,target}` — cc65 binaries search `../lib` etc. relative to `bin/` first, then compiled-in paths; test.sh must prove lookup works with no `CC65_HOME`). Also `make -C doc` is skipped.
    
*   alpine: `build-base`. macOS: none.
    
*   test: `cl65 -t c64 hello.c -o hello.prg` and `ca65`/`ld65` round-trip on `hello.s`.
    
*   note: upstream releases are rare (V2.19 → 2020); snapshot support is the top future-work item for this tool.
    

### sdcc

*   upstream: `sourceforge`, project `sdcc`, `file_regex = '^sdcc-src-(?P<version>\d+\.\d+\.\d+)\.tar\.gz$'`, `min_version = "4.4.0"`.
    
*   source url: `https://sourceforge.net/projects/sdcc/files/sdcc/{version}/sdcc-src-{version}.tar.gz/download`, `strip_components = 1`.
    
*   build: `./configure --prefix="$PREFIX" --disable-pic14-port --disable-pic16-port --disable-non-free --disable-ucsim --disable-doc` (keep z80/z180/r2k/gbz80/ez80/tlcs90/mos6502/mos65c02/stm8/mcs51/… as they cost little; drop `--disable-ucsim` if the simulator is wanted). `make -j$NPROC && make install`. Verify relocatability: sdcc locates `include/` and `lib/` relative to the binary via its `bin/../share/sdcc` convention — test.sh compiles from an arbitrary path.
    
*   alpine: `build-base boost-dev boost-static bison flex zlib-dev zlib-static texinfo` (trim after first successful build). macOS: `brew install boost bison flex`; force `PATH` to Homebrew bison (Apple's is too old); confirm no boost dylib is linked (boost usage is header-only in sdcc; `check-portability` enforces).
    
*   `timeout_minutes = 90`.
    
*   test: `sdcc -mz80 -c hello.c`, `sdcc -mmos6502 -c hello.c`, `sdasz80`/`sdldz80` round-trip.
    

### oscar64

*   upstream: `github`, `drmortalwombat/oscar64`, `tag_regex = '^v?(?P<version>\d+\.\d+(?:\.\d+)?)$'` (verify actual tag scheme at implementation time), `min_version` = the newest release at implementation time (history not needed).
    
*   build: `make -C make -j$NPROC CXX=$CXX`; `install -Dm755 bin/oscar64 $PREFIX/bin/oscar64`; `cp -r include $PREFIX/include`; copy `samples/` optionally.
    
*   alpine: `build-base`. macOS: none.
    
*   expect Makefile patches (hard-coded flags); keep in `patches/`.
    
*   test: compile `samples/hello/hello.c` for C64 and check `.prg` produced.
    

### kickc

*   upstream: `gitlab`, `camelot/kickc`, `tag_regex = '^(?P<version>\d+\.\d+\.\d+)$'` (verified: tags are bare, e.g. `0.8.6`), `min_version = 0.8.6`.
    
*   `platform_independent = true`, `runtime_requirements = ["java>=11"]` (bytecode floor verified as Java 8 — multi-release jar module-info aside; 11 kept as a conservative claim).
    
*   `build.mode = "repackage"` — **verified**: every GitLab release carries a `Binary` asset link → shortener → stable GitLab wiki upload (`kickc_{version}.zip`), resolved at fetch time via the releases API (`source.release_asset = "Binary"`; the effective post-redirect URL is recorded for the notice). Zip root `kickc/` ships `bin/`, `jar/` (kickc jar + dependency jars), `include/`, `lib/`, `fragment/`, `target/`, `LICENSE.txt`, `NOTICE.txt` (+ examples and the manual PDF, which are not installed). Source-mode fallback exists (`mvn package`, pom targets Java 17) but is not the shipped path.
    
*   output layout: `bin/kickc` = our POSIX-sh launcher (spec §7.2) reproducing upstream's **required** args `-F/-I/-L/-P` (verified: `KICKC_*` env alone is not read by the app — without `-P` the platform list is empty) + `jar/ fragment/ include/ lib/ target/` + upstream `NOTICE.txt`.
    
*   test: `kickc -V` (version) and `kickc -p c64 hello.c` in a temp dir → non-empty `hello.asm` (platform flag is `-p`, **not** `-t`; JRE available on all GitHub runners).


* * *

## 11. Adding a tool — `scripts/new-tool.sh <tool>`

1.  `gh repo create retropack/<tool> --public --description "…" --template retropack/tool-template` (the template repo holds the stub workflow + README placeholder). Or copy `templates/tool-repo/` and push.
    
2.  Scaffold `tools/<tool>/{tool.toml,build.sh,test.sh,fixtures/}` in the brain from templates; developer fills in.
    
3.  Open PR in brain; `ci.yml` validates manifest schema and shellcheck.
    
4.  After merge: `gh workflow run watch.yml -f tool=<tool>` → first releases appear. Add the tool to the brain README table (a generator script keeps it in sync from `tool.toml`s).
    

The App is installed org-wide, so no credential step.

* * *

## 12. Maintenance policy (deliberately minimal)

*   **Floating versions everywhere**: runner labels `*-latest`/`ubuntu-24.04-arm`, `alpine:3`, actions by major tag, brain workflow referenced `@main`. No Dependabot version-update PRs; Dependabot _security alerts_ only.
    
*   Smoke + acceptance tests are the safety net for environment drift: a broken environment produces a failed build (issue), never a broken release.
    
*   Branch protection on brain `main`: `ci.yml` must pass; no other rules (solo project).
    
*   Expected human touchpoints: (1) a `build-failure` issue when an upstream changes its build system; (2) adding a tool; (3) nothing else.
    

* * *

## 13. Open items to verify during M1

- [x] Which checksum file form mise's github backend discovers (`SHA256SUMS` vs `<asset>.sha256`); keep one. — **Resolved (M1 E2E): neither.** mise verifies via the GitHub API asset digest (`using GitHub API digest for checksum verification`); per-asset `.sha256` dropped, `SHA256SUMS` kept for humans (§7.1 updated).
- [x] mise attestation verification passes for releases created in the tool repo by the reusable workflow (builder identity is `retropack/<tool>/.github/workflows/release.yml` → `retropack/retropack/.github/workflows/build.yml`). — **Resolved:** `mise install` logs `[2/3] ✓ GitHub artifact attestations verified`; the bundle predicate names `retropack/cc65/.github/workflows/release.yml` with `builder.id = retropack/retropack/.github/workflows/build.yml@refs/heads/main`, and the signing certificate SANs carry both workflow URIs. (`gh attestation verify` on one workstation failed in its TUF-root fetch — client-side, same bundle passes mise's verifier.)
- [x] cc65 relocatable data-dir lookup without `CC65_HOME` from a mise install dir. — **Resolved:** V2.19 has no exe-relative lookup (verified), so archives ship `bin/<tool>` launchers exporting `CC65_HOME` (spec §7.2 wrapper mechanism) + real binaries in `libexec/`; `test.sh` passes from an arbitrary cwd and against a fresh `mise install github:retropack/cc65@2.19` with `CC65_HOME` unset.
- [x] sdcc relocatable `include/lib` lookup; actual minimal Alpine package set; build time within budget. — **Resolved locally (linux-x86_64):** `bin/../share/sdcc` lookup proven by `test.sh` run from a temp dir; Alpine set = `build-base boost-dev boost-static bison flex zlib-dev zlib-static texinfo` (build green, well under the 90-minute budget); plus M1 fixes found en route: bundled sdbinutils needed `AM_LDFLAGS=-all-static` (libtool swallowed plain `-static`) and `lib/*.la` are removed post-install (absolute build paths, §6.4). CI-matrix run still pending.
- [x] `docker run` availability/perf on `ubuntu-24.04-arm`. — **Resolved:** green runs 36310688371 + 36312373408; full fetch→build→test→portability→package within the job timeout.
- [x] Actual tag/release schemes for oscar64 and kickc. — **Resolved:** oscar64 = `v`-prefixed tags (`v1.32.273`, built green); kickc = bare version tags (`0.8.6`) on GitLab releases.
- [x] Whether kickc GitLab releases carry a distribution zip (`build.mode = repackage` vs `source`) — **resolved (M3):** yes — each release's `Binary` asset link → GitLab wiki upload `kickc_{version}.zip`; shipped as `mode = "repackage"`, resolved at fetch time (see §10 kickc).
- [ ] SourceForge `best_release.json` + RSS give complete-enough version lists for backfill (else restrict `min_version` to current). — **Partially resolved:** `best_release.json` yields the latest fine (tass64 → 1.60.3243, sdcc → 4.6.0); `rss?path=/` returned no file titles for sdcc, so backfill *depth* stays unproven.
- [x] mise picks the identical-bytes noarch archives correctly on all three platforms. — **Resolved (M3):** kickc 0.8.6 fan-out published three platform assets with byte-identical sha256 (`d6a42072…`); `accept` green on ubuntu-latest, ubuntu-24.04-arm and macos-latest (each installed its own platform-named copy and passed `test.sh`).

* * *

## 14. Future work (explicitly out of v1)

*   **Snapshot builds** (esp. cc65): date versions `2.19.<yyyymmdd>` built from upstream `master`, published as prereleases so `latest` stays on stable; users opt in with `prerelease = true`.
    
*   **Z80 tools**: z88dk, sjasmplus, rasm, pasmo — same contract, just new `tools/<name>/`.
    
*   **Extra platforms**: `macos-x86_64` (`macos-13`/`macos-15-intel` while available), `windows-x86_64` (MSYS2/MinGW static).
    
*   **packslip manifests** signed in the tool repo workflow → eligibility for a mise registry short name (`cc65 = "…"` without `github:`), plus shell completions.
    
*   **aqua registry** entries as an alternative registry route.
    
*   Brain README auto-generation with per-tool version badges.
    

* * *

## 15. Milestones

*   **M1 — Skeleton + cc65 end-to-end**: org, App, brain repo, template repo, `watch.yml`, `build.yml`, `publish.sh`, cc65 manifest/build/test; acceptance green on all 3 platforms; resolve §13 items.
    
*   **M2 — tass64, oscar64** (simple C/C++ builds).
    
*   **M3 — kickc** (noarch path, wrapper script).
    
*   **M4 — sdcc** (heavy build, macOS bison/boost handling).
    
*   **M5 — Hardening**: failure→issue flow verified end-to-end, keepalive verified (`gh api …/workflows/watch.yml` shows `state: active`), README with install matrix.