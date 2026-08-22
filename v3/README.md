# palaia v3

**Status: planning.** This directory contains everything belonging to palaia v3 —
a ground-up rewrite with a much larger scope than v2 ("Home Assistant for AI").

Nothing in here is released. palaia v2 (the repo root) remains the stable product;
v2 hotfixes happen on the `v2-maintenance` branch.

## Navigation

| Document | Purpose |
|----------|---------|
| [MASTERPLAN.md](MASTERPLAN.md) | **Start here.** Vision, product pillars, architecture, roadmap, open decisions |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Work breakdown, execution protocol for agents, model/effort matrix, phase gates |
| [specs/](specs/) | Executable SPECs (one SPEC = one branch = one PR), Phase 0 + 1 |
| [research/](research/) | Research dossiers the plan is grounded in |
| [decisions/](decisions/) | Architecture Decision Records (ADRs) for v3 |
| [docs/design/](docs/design/) | UX north star: design system, principles, and HTML mockups of the key screens |

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

Prerequisites: [`uv`](https://docs.astral.sh/uv/), Node 22+, and
[`just`](https://github.com/casey/just) (or run the underlying commands
directly — see `v3/justfile`).

```bash
cd v3
just setup   # uv sync --all-packages; npm ci in web/
just test    # pytest + vitest
just lint    # ruff, mypy, eslint, tsc
just dev     # Vite dev server for the web app
just build   # production build of the web app
```

Equivalent raw commands, if you don't have `just`:

```bash
cd v3 && uv sync && uv run pytest
cd v3/web && npm ci && npm test && npm run build
```

CI: [`.github/workflows/v3-ci.yml`](../.github/workflows/v3-ci.yml) runs the
Python and web checks above on any push/PR to `main` that touches `v3/**`.
It is independent of the v2 `ci.yml` (repo root), which ignores `v3/**`
changes.

## Ground rules

- v3 is developed **only** inside `v3/`. No imports or shared tooling with v2 code.
- `MASTERPLAN.md` is the source of truth for scope and roadmap. Changes to scope go
  through a PR that updates it.
- Significant technical decisions are recorded as ADRs in `decisions/` before
  implementation starts.
