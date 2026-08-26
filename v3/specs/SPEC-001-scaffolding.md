---
id: SPEC-001
title: v3 scaffolding, tooling, CI lane
phase: 0
depends_on: [SPEC-006]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-001: v3 scaffolding, tooling, CI lane

## Goal
A `v3/` workspace in which every later SPEC can be implemented, tested and
CI-verified — without touching anything of v2.

## Deliverables
1. **uv workspace** rooted at `v3/pyproject.toml` (virtual root; members
   `v3/server` now, more later). Python ≥ 3.12, hatchling, pytest, ruff
   (line length 100), mypy (strict on new code).
2. Package `v3/server/` (`palaia_hub` import name): empty-but-importable, one
   placeholder module, one passing test.
3. `v3/web/`: Vite + React + TypeScript + Tailwind app skeleton; `npm test`
   (vitest) and `npm run build` pass; no UI beyond a placeholder page.
4. **CI workflow `.github/workflows/v3-ci.yml`**: triggers on push/PR to `main`
   with `paths: ['v3/**']`; jobs: python (ruff, mypy, pytest) and web (eslint,
   tsc, vitest, build). Must NOT run for v2-only changes; v2's `ci.yml` gets
   `paths-ignore: ['v3/**']` — check CONTRIBUTING notes about required checks
   and mention the needed branch-protection adjustment in the PR description.
5. `v3/justfile` (or Makefile): `just test`, `just lint`, `just dev` documented
   in `v3/README.md`.

## Acceptance criteria
- [ ] `cd v3 && uv sync && uv run pytest` passes on a fresh clone
- [ ] `cd v3/web && npm ci && npm test && npm run build` passes
- [ ] v3-ci.yml runs and is green on the PR; ci.yml does not run when only
      `v3/**` changed (verify in the PR's checks list)
- [ ] no file outside `v3/` and `.github/workflows/` touched
- [ ] `v3/README.md` navigation updated (dev setup section)

## Non-goals
No application code, no Docker (SPEC-112), no dashboard design (SPEC-109).

## Execution notes
Follow `v3/IMPLEMENTATION.md` §1. Read AGENTS.md two-track rules first.
