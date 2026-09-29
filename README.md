# retropack

retropack distributes prebuilt, redistributable cross-development tools for
retro targets (6502 first, Z80 later) so they can be installed individually
with [mise](https://mise.jdx.dev) via its built-in `github:` backend — no
compiler, Java, or other toolchain required on the user's machine (JVM tools
need a JRE on PATH).

```toml
[tools]
"github:retropack/cc65"   = "2.19"
"github:retropack/tass64" = "latest"
```

| Tool | Upstream | Licence | Notes |
| --- | --- | --- | --- |
| `tass64` | SourceForge `tass64` | GPL-2.0 | Binary is `64tass` |
| `cc65` | GitHub `cc65/cc65` | Zlib | Needs `lib/ include/ asminc/ cfg/ target/` beside `bin/` |
| `sdcc` | SourceForge `sdcc` | GPL-2.0 | Heaviest build; 6502/Z80 ports only |
| `oscar64` | GitHub `drmortalwombat/oscar64` | GPL-3.0 | Needs `include/` beside `bin/` |
| `kickc` | GitLab `camelot/kickc` | MIT | JVM tool; needs JRE ≥ 11 on PATH |

The specification lives in [`docs/specs/draft-1.md`](docs/specs/draft-1.md).

## Git hooks

Quality gates run via [hk](https://hk.jdx.dev) on every commit:
**shellcheck** (`scripts/`, `tools/`), **yamllint** + **actionlint** (workflow
YAML), and **pytest** via [uv](https://docs.astral.sh/uv) (Python logic,
workflow contracts, TOML schema — every `tool.toml` and root `.toml` must
parse; test deps are exact pins in `scripts/run-tests.py`'s inline metadata).

- `hk check` — run all checks manually
- `HK=0 git commit …` — bypass for a single commit
- New clone setup: `mise install` (brings hk, uv, shellcheck, yamllint, actionlint), then `hk install`

CI runs the identical gate (`hk check --all`) with the identical tool versions —
both are sourced from `mise.toml`, so local and GitHub runners can't drift apart.

