# ADR-001: v2 and v3 coexist in one repository, strictly separated

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** cwendler

## Context

palaia v3 is a full rewrite with a larger scope than v2. v2 has few users but must
remain available: installable from PyPI, checkout-able from git, and hotfix-able if a
critical bug surfaces. Creating a second repository would split history, issues, stars,
and the PyPI/npm package identity.

## Decision

One repository, two strictly separated tracks:

1. **v2 (maintenance-only)** stays at the repo root, untouched. The exact v2.8.0
   release state is preserved three ways: PyPI (`pip install palaia==2.8.0`), the git
   tag `v2.8.0`, and the branch **`v2-maintenance`** (created from that tag). Hotfixes
   are developed against `v2-maintenance` and tagged from it (`v2.8.1`, …).
   `publish.yml` triggers on `v*` tags and builds from the tag, so v2 releases never
   involve `main`.
2. **v3 (active)** lives entirely under `v3/` on `main` — planning documents first,
   code packages later. No imports, shared configs, or shared build tooling across the
   boundary; a PR touches exactly one track.
3. At cutover (v3 stable), the v2 code is removed from `main`; tag and maintenance
   branch continue to carry it.

Supporting changes made with this ADR: CI (`ci.yml`) also triggers for
`v2-maintenance` pushes/PRs; the `.hooks/pre-push` hook blocks direct pushes to
`v2-maintenance`; `AGENTS.md`/`CONTRIBUTING.md` document the two-track workflow;
`.clawhubignore` excludes `v3/` from the v2 ClawHub package.

## Alternatives considered

- **New repository for v3** — clean, but loses package identity, history, and requires
  users to migrate watchers/issues; explicitly rejected by the owner.
- **v3 on a long-running branch** — invisible on the repo landing page, permanent
  merge-conflict risk with v2 files, CI complexity.
- **Monorepo restructure now (move v2 into `legacy/`)** — would break v2's root
  packaging (`pyproject.toml` paths) for zero benefit while v2 still releases.

## Consequences

- v3 development is visible on `main` from day one; v2 stays release-capable.
- GitHub branch protection for `v2-maintenance` must be configured in repo settings
  (the local hook is only a soft guard) — owner action, cannot be done from CI.
- When v3 code lands, CI will be split into per-track workflows with path filters
  (`v2-ci.yml` / `v3-ci.yml`) and the required-checks configuration updated to match.
