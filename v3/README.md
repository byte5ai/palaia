# palaia v3

**Status: release candidate (`3.0.0-rc4`, see [VERSION](VERSION)).** This
directory contains everything belonging to palaia v3 — a ground-up rewrite
with a much larger scope than v2 ("Home Assistant for AI"). The Phase-5
gate is held (`IMPLEMENTATION.md` §6, 2026-08-26; the two owner actions it
named were withdrawn on 2026-10-02); `RELEASING.md` is the ordered path from
here to a final, non-candidate `3.0.0`.

Not yet tagged `3.0.0`. palaia v2 (the repo root) is retired; only critical
fixes land, on the `v2-maintenance` branch.

## Navigation

| Document | Purpose |
|----------|---------|
| [MASTERPLAN.md](MASTERPLAN.md) | **Start here.** Vision, product pillars, architecture, roadmap, open decisions |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Work breakdown, execution protocol for agents, model/effort matrix, phase gates |
| [specs/](specs/) | Executable SPECs (one SPEC = one branch = one PR), Phase 0 + 1 |
| [research/](research/) | Research dossiers the plan is grounded in |
| [docs/intel/](docs/intel/) | Competitive reads on neighbouring products, and what they mean for our roadmap |
| [decisions/](decisions/) | Architecture Decision Records (ADRs) for v3 |
| [docs/design/](docs/design/) | UX north star: design system, principles, and HTML mockups of the key screens |
| [docs/external-servers.md](docs/external-servers.md) | Connecting other people's MCP servers, and where their credentials live |
| [SECURITY.md](SECURITY.md) | **Supported versions, and how to report a vulnerability** |
| [docs/security/](docs/security/) | Threat model (as built) and the dependency policy |
| [VERSION](VERSION) / [CHANGELOG.md](CHANGELOG.md) | The current release candidate's version, and what's in it, by capability |
| [RELEASING.md](RELEASING.md) | The ordered checklist from "the gate is held" to a tagged, published `3.0.0` |
| [docs/client-matrix-results.md](docs/client-matrix-results.md) | Real, run evidence for every phase gate, including the Phase-5 RC (§9) |

## Dev setup

Layout established by SPEC-001:

- `v3/server/` — Python `palaia_hub` package (part of a `uv` workspace rooted
  at `v3/pyproject.toml`). Python ≥3.12, hatchling, pytest, ruff (line length
  100), mypy (strict).
- `v3/web/` — Vite + React + TypeScript + Tailwind dashboard skeleton, tested
  with vitest and linted with eslint.
- `v3/spikes/` — self-contained spike code (SPEC-002, SPEC-003). Deliberately
  **not** a member of the uv workspace, so a spike's throwaway dependencies
  never affect `v3/server`.

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Node 26+, and
[`just`](https://github.com/casey/just) (or run the underlying commands
directly — see `v3/justfile`).

```bash
cd v3
just setup   # uv sync --all-packages; npm ci in web/
just test    # pytest + vitest
just lint    # ruff check + format check, mypy, eslint, tsc
just fmt     # ruff format (Python)
just dev     # Vite dev server for the web app
just build   # production build of the web app
```

**Formatting is enforced** (issue #407): CI runs `ruff format --check .`
next to `ruff check` and `mypy`. Run `just fmt` (or `uv run ruff format .`)
before you push. The one commit that reformatted the whole tree is listed
in `.git-blame-ignore-revs`; to have `git blame` skip it, run
`git config blame.ignoreRevsFile .git-blame-ignore-revs` once.

Equivalent raw commands, if you don't have `just`:

```bash
cd v3 && uv sync && uv run pytest
cd v3/web && npm ci && npm test && npm run build
```

CI: [`.github/workflows/v3-ci.yml`](../.github/workflows/v3-ci.yml) runs the
Python and web checks above on any push/PR to `main` that touches `v3/**`;
the workflow itself starts on every push/PR to `main` so its `v3-ci-required`
gate always reports (the check `main` requires), and lanes whose area is
untouched are skipped. It is independent of the v2 `ci.yml` (repo root), whose
lanes skip when only `v3/**` changed.

### Running the packaged hub locally

`v3/deploy/` (SPEC-112) has the Docker packaging: a multi-stage `Dockerfile`
(web build → uv-installed hub → nginx + hub runtime), `docker-compose.yml`,
an optional `install.sh` convenience script, and the mDNS announcer. See
[`v3/deploy/README.md`](deploy/README.md) for the one-liner, the compose
file, mDNS caveats (containerized networking honestly documented), and the
manual verification checklist. Images are published to
`ghcr.io/byte5ai/palaia-hub` by
[`.github/workflows/v3-release.yml`](../.github/workflows/v3-release.yml)
(`edge` on `main`, `stable`/`beta` on `v3.*` tags, `linux/amd64` +
`linux/arm64`).

## Ground rules

- v3 is developed **only** inside `v3/`. No imports or shared tooling with v2 code.
- `MASTERPLAN.md` is the source of truth for scope and roadmap. Changes to scope go
  through a PR that updates it.
- Significant technical decisions are recorded as ADRs in `decisions/` before
  implementation starts.
