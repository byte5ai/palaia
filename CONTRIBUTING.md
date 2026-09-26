# Contributing to palaia

Thanks for your interest in contributing to palaia!

palaia has two development tracks (details under [Two development tracks](#two-development-tracks)):
new work goes into **v3**, under `v3/` on `main`; **v2**, the code at the repo root, only
takes critical hotfixes, on the `v2-maintenance` branch. This file describes contributing
on `main`. For a v2 hotfix, follow `CONTRIBUTING.md` on `v2-maintenance` instead — it
carries v2's setup, versioning and release process.

## Development Setup

```bash
git clone https://github.com/byte5ai/palaia.git
cd palaia
git config core.hooksPath .hooks   # pre-push hook: blocks direct pushes to protected branches
cd v3
just setup   # uv sync --all-packages; npm ci in web/
just test    # pytest + vitest
just lint    # ruff check, mypy, eslint, tsc
```

Prerequisites ([`uv`](https://docs.astral.sh/uv/), Node 22+,
[`just`](https://github.com/casey/just)) and the equivalent raw commands are in
[`v3/README.md`](v3/README.md#dev-setup).

## Code Style

v3 Python is linted with [ruff](https://docs.astral.sh/ruff/) (line length 100) and
type-checked with mypy in strict mode; both gate CI. Configuration is in
`v3/pyproject.toml` and `v3/server/pyproject.toml`. `ruff format` is not enforced yet —
format the files you touch; [`v3/README.md`](v3/README.md#dev-setup) records the
decision and when it changes. The web app is linted with eslint and type-checked
with `tsc` (`just lint` runs all four).

## Reporting Bugs

Open a [GitHub Issue](https://github.com/byte5ai/palaia/issues). Include:

- Which palaia you run: the v3 hub (release or image tag) or v2 (`palaia --version`,
  plus `palaia doctor --json` output and `python --version`)
- Steps to reproduce
- Expected vs actual behavior

## Branch Policy

**`main` and `v2-maintenance` are protected.** Direct pushes are not allowed. All changes go through pull requests.

| Rule | Setting |
|------|---------|
| Direct push to main / v2-maintenance | Blocked |
| Pull request required | Yes |
| CI must pass | Yes (test 3.11) |
| Force push | Blocked |
| Owner bypass | Yes (emergencies only) |

### Two development tracks

| Track | Where | Base branch for PRs | What belongs there |
|-------|-------|---------------------|--------------------|
| **v2** (maintenance) | repo root (`palaia/`, `tests/`, `packages/`) | `v2-maintenance` | Critical hotfixes only (security, data loss, broken release) |
| **v3** (active) | `v3/` | `main` | Everything new |

- **v2 (stable, maintenance-only):** the code at the repo root (`palaia/`, `tests/`,
  `packages/openclaw-plugin/`, `docs/`, `skills/`). Feature development is frozen.
  Only critical hotfixes (security, data loss, broken release) are made. Hotfix PRs
  target the **`v2-maintenance`** branch — never `main`. Release tags `v2.x.y` are cut
  from `v2-maintenance`.
- **v3 (active development):** lives entirely under **`v3/`** on `main`.
  `v3/MASTERPLAN.md` is the source of truth for v3 scope and roadmap. Significant v3
  decisions are recorded in `v3/decisions/` as ADRs.

**Hard separation rules:**

- Never import/require across the boundary: v2 code must not depend on `v3/` and vice versa.
- No shared build tooling, lockfiles, or configs between the tracks.
- A PR touches files of exactly one track (the only exception: intentional cross-references
  in top-level docs such as the README pointer to v3).
- v3 work must not modify v2 root files (`pyproject.toml`, `palaia/`, `packages/`, …).

**v3 conventions:**

- Repository language is **English** — code, comments, docs, ADRs, commit messages.
- Every user-facing v3 feature must be checked against the standing design question
  "is an MCP App the right or a sensible surface for this?" — see
  `v3/MASTERPLAN.md` §4 (rule 8) and §5.7.

**v2 hotfix release:** branch from `v2-maintenance`, PR back into `v2-maintenance`,
bump the version files listed in `CONTRIBUTING.md` on that branch, then tag (`v2.8.1`)
from `v2-maintenance`. `publish.yml` builds from the tag — the root packaging on `main`
is not involved.

**Workflow:**
1. Create a branch from the track's base branch: `main` for v3,
   `v2-maintenance` for a v2 hotfix
2. Develop, commit, push to your branch
3. Open a PR against that same base branch
4. CI runs automatically
5. Merge after CI passes

**Branch naming:**
- `feat/...` — new features
- `fix/...` — bug fixes
- `refactor/...` — restructuring without behavior change
- `docs/...` — documentation only
- `chore/...` — maintenance, cleanup

## Submitting Pull Requests

1. **Create a branch** from `main`: `git checkout -b feat/my-feature origin/main`
2. **Write tests** for new functionality
3. **Run the checks** from `v3/`: `just test` and `just lint`
4. **Commit** with a clear message (see Commit Convention below)
5. **Open a PR** against `main`

### PR Requirements

- `just test` passes and `just lint` is clean (`v3-ci.yml` runs the same checks on every PR that touches `v3/`)
- New features need tests
- One logical change per PR; a short title (<70 chars) with a conventional prefix
- No force pushes, no skipped hooks (`--no-verify`)
- Never commit secrets (`.env`, API keys, tokens, credentials)

## Commit Convention

Prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`, `release:`, `dev:`.

v3 changes carry the `(v3)` scope:

```
feat(v3): add the Telegram screen to the dashboard
fix(v3): never issue a token id that starts with a dash
docs(v3): describe the dashboard's Telegram screen
release(v3): 3.0.0-rc2 — version bump, changelog, release notes
```

## Releases

v3 is versioned in `v3/VERSION` and released through `v3-cut-release.yml`; the
checklist is [`v3/RELEASING.md`](v3/RELEASING.md) and the history is
[`v3/CHANGELOG.md`](v3/CHANGELOG.md). v2's versioning and release process (PyPI,
ClawHub, npm) live in `CONTRIBUTING.md` on `v2-maintenance`.

### CI Workflows

| Workflow | Trigger | What it does |
|----------|---------|-------------|
| `v3-ci.yml` | Push/PRs to `main` touching `v3/**` or a `v3-*` workflow | Python (ruff, mypy, pytest), web, SDK, e2e, MCP bundle, docs site |
| `v3-release.yml` | Push to `main`, `v3.*` tags | Hub container image (`edge` on `main`, `stable`/`beta` on tags) |
| `v3-cut-release.yml` | Manual dispatch | Tags a v3 release and triggers the image builds |
| `v3-pi-image.yml` | `v3.*` tags, manual dispatch | Raspberry Pi appliance image |
| `ci.yml` | Push/PRs to `main` or `v2-maintenance`, ignoring `v3/**` | v2: ruff + pytest (3.9-3.12) + plugin vitest |
| `publish.yml` | `v2.*` tags | v2 PyPI publish (all v2 tags) + npm publish (stable only) |
| `track-label.yml` | New issues/PRs, daily sweep, manual dispatch | Adds the `v2` or `v3` label to every issue and PR that has neither |

`publish.yml` is v2-only: the tag filter is `v2.*` (and every job re-checks the
`refs/tags/v2.` prefix), so a v3 release tag — `v3.*`, e.g. `v3.3.0.0` — never
triggers a v2 PyPI/npm publish.

Every issue and PR carries exactly one track label, `v2` or `v3`; `v2` marks work
on the retired v2 code. `track-label.yml` guesses it (PRs by base branch and
changed files, issues by title — start a v2 issue's title with `v2:`), and a label
set by hand is never overridden.

## Architecture

How v3 works — components, data flows, and the evidence behind its claims — is in
[`v3/docs/how-it-works.md`](v3/docs/how-it-works.md); `v3/MASTERPLAN.md` holds scope
and roadmap. Significant v3 decisions are recorded as ADRs in `v3/decisions/`.

## Documentation

| Document | Audience | Purpose |
|----------|----------|---------|
| `README.md` | Users + Contributors | Pitch, quickstart, links |
| `CONTRIBUTING.md` | Contributors | This file |
| `v3/README.md` | Contributors | v3 dev setup and ground rules |
| `v3/MASTERPLAN.md` | Contributors | v3 scope and roadmap |
| `v3/site/docs/` | Users | The v3 documentation site |
