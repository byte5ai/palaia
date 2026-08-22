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

## Ground rules

- v3 is developed **only** inside `v3/`. No imports or shared tooling with v2 code.
- `MASTERPLAN.md` is the source of truth for scope and roadmap. Changes to scope go
  through a PR that updates it.
- Significant technical decisions are recorded as ADRs in `decisions/` before
  implementation starts.
