# Agent Instructions

These rules apply to all AI agents working on this repository (Codex, Claude, Copilot, etc.).

## Git Workflow

- **Never push directly to `main`.** All changes go through feature branches and pull requests.
- **Branch naming:** `feat/`, `fix/`, `refactor/`, `docs/`, `chore/` prefixes.
- **Conventional commits:** `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `release:`, `dev:`.
- **Never force-push** to any shared branch.
- **Never commit secrets** (.env, API keys, tokens, credentials).
- **Never skip hooks** (`--no-verify`).

## Pull Requests

- Keep PR titles short (<70 chars), use conventional prefix.
- One logical change per PR.
- Ensure tests pass before requesting merge.

## Project

- **Python + TypeScript** monorepo: `palaia/` (Python CLI/core) + `packages/openclaw-plugin/` (TS plugin).
- Tests: `python3 -m pytest tests/ -q` and `cd packages/openclaw-plugin && npx vitest run`.
- Dev server runs on **devhost** (Tailscale) — never use `localhost`.

## Pre-push Hook

A `.hooks/pre-push` hook blocks direct pushes to `main`/`master`. Override only when explicitly instructed:
```bash
ALLOW_PUSH_TO_MAIN=1 git push origin main
```

## Two Development Tracks (v2 / v3)

This repository hosts two strictly separated lines of development:

- **v2 (stable, maintenance-only):** the code at the repo root (`palaia/`, `tests/`,
  `packages/openclaw-plugin/`, `docs/`, `skills/`). Feature development is frozen.
  Only critical hotfixes (security, data loss, broken release) are made. Hotfix PRs
  target the **`v2-maintenance`** branch — never `main`. Release tags `v2.x.y` are cut
  from `v2-maintenance`.
- **v3 (active development):** lives entirely under **`v3/`** on `main`. Currently in
  the planning phase; code packages will be added under `v3/` as they are created.
  `v3/MASTERPLAN.md` is the source of truth for v3 scope and roadmap. Significant v3
  decisions are recorded in `v3/decisions/` as ADRs.

**v3 project conventions:**

- Repository language is **English** — code, comments, docs, ADRs, commit messages.
- Every user-facing v3 feature must be checked against the standing design question
  "is an MCP App the right or a sensible surface for this?" — see
  `v3/MASTERPLAN.md` §4 (rule 8) and §5.7.

**Hard separation rules:**

- Never import/require across the boundary: v2 code must not depend on `v3/` and vice versa.
- No shared build tooling, lockfiles, or configs between the tracks.
- A PR touches files of exactly one track (the only exception: intentional cross-references
  in top-level docs such as the README pointer to v3).
- v3 work must not modify v2 root files (`pyproject.toml`, `palaia/`, `packages/`, …).
