# Dependency policy and audit (v3)

SPEC-502 deliverable #2, the dependency half: what palaia v3 depends on, how
those dependencies are pinned, how they are audited, and what happens when an
advisory lands.

## The pinning rules

| Ecosystem | Where | How it is pinned | Why |
|---|---|---|---|
| Python, runtime | `v3/server/pyproject.toml` | Floors (`fastapi>=0.115`), resolved to exact versions by `v3/uv.lock` | The lockfile is the pin; floors say what the code needs |
| Python, one exception | `fastmcp==3.4.7` | **Exact** | The protocol layer. A minor bump changes MCP behavior we assert against; upgrading it is a deliberate act with its own PR |
| Python, dev | `[project.optional-dependencies] dev` | Floors, resolved by the same lockfile | |
| Node, dashboard | `v3/web/package.json` + `package-lock.json` | The lockfile is the pin; CI installs with `npm ci` | |
| Node, build tooling | `v3/tools/build-mcpb/package-lock.json` | Same | Build-time only; nothing here reaches a user's machine |
| Container base | `v3/deploy/Dockerfile` | `python:3.12-slim`, `node:22-slim` | Rebuilt on every release, so a base-image fix arrives with the next image |

**One lockfile per track.** `v3/uv.lock` covers the whole v3 Python workspace
and nothing outside it; v2's dependencies are separate, per `AGENTS.md`.
`uv lock --check` runs in CI, so a `pyproject.toml` edit that was never
locked fails the build rather than resolving differently on someone else's
machine.

## How auditing runs

| Check | Command | Where |
|---|---|---|
| The lockfile matches the manifests | `uv lock --check` | CI, every push |
| Python advisories | `pip-audit` against the exported lockfile | CI, every push (advisory job) |
| Node advisories, dashboard | `npm audit` in `v3/web` | CI, every push (advisory job) |
| Node advisories, build tooling | `npm audit` in `v3/tools/build-mcpb` | CI, every push (advisory job) |

The advisory job **reports without gating**, and that is a deliberate,
uncomfortable choice: a third party publishing an advisory at 3am would
otherwise turn every branch red until someone woke up, which trains people
to ignore a red build. What gates instead is the policy below — a
high-or-critical advisory in something a user actually runs is a release
blocker, checked at release time when a human is present.

## What happens when an advisory lands

| Where the advisory is | Response | Deadline |
|---|---|---|
| A **runtime** Python or dashboard dependency, high or critical | Upgrade, or remove the dependency; **blocks the next release** | 7 days |
| A runtime dependency, moderate or low | Upgrade at the next dependency sweep | Next minor release |
| A **development or build-time** dependency, any severity | Upgrade when an upgrade exists; recorded here if it does not | Next dependency sweep |
| The container base image | Rebuild; the release workflow rebuilds from the current base anyway | Next release |
| An MCP server a *user* installed | Not ours to fix. Report it to its maintainer; the marketplace entry is flagged if the hub makes it worse | — |

A dependency sweep runs at each phase gate and before every release: `uv
lock --upgrade`, `npm update` within the declared ranges, then the full test
suite. Bumping `fastmcp` is never part of a sweep — it gets its own PR.

## Audit results at the time of this pass

Run on 2026-08-25, against the current lockfiles:

| Target | Result |
|---|---|
| Python runtime dependencies (`uv export --no-dev`) | **No known vulnerabilities** |
| Python including dev dependencies | **No known vulnerabilities** |
| `v3/web` (8 runtime, 723 dev packages) | **0 vulnerabilities** |
| `v3/tools/build-mcpb` (1 runtime, 55 dev packages) | **0 vulnerabilities** — see below |

### Resolved: the `tmp` finding (formerly tracked as issue #264)

`tmp <= 0.2.5` (GHSA-52f5-9888-hmc6, GHSA-ph9p-34f9-6g65 — arbitrary
temporary file write via a symlinked `dir`, and path traversal via an
unsanitized prefix) reached `v3/tools/build-mcpb` through
`@anthropic-ai/mcpb → @inquirer/prompts → @inquirer/editor →
external-editor → tmp`, pinned at `tmp@0.0.33` by that chain's own
`package.json` ranges. `@anthropic-ai/mcpb` had no newer release to pick up
a patched `@inquirer` chain — but `tmp@0.2.6` (current: `0.2.7`) fixes both
advisories on its own, and nothing in `external-editor`'s use of `tmp`
needed the older major. A `package.json` **`overrides`** entry pins
`tmp` to `^0.2.6` underneath the unpatched chain, narrower than waiting on
an upstream `@anthropic-ai/mcpb` release: it changes only the one
transitive package the advisories are actually about, not the chain
carrying it. `npm audit` is clean; `npm ci && npm run build` and the
proxy's own test suite still pass unchanged.

This was accepted for a time (build-time devDependency only, reached only
through an interactive prompt the packer's non-interactive `mcpb validate`/
`mcpb pack` never invokes) — see the closed issue for that original
reasoning — but a clean override was available, so it no longer needs to
carry into 3.0 on a review trigger.

## Reproducing the audit

```bash
cd v3
uv lock --check
uv export --no-hashes --no-dev -o /tmp/runtime-reqs.txt
uv run --with pip-audit pip-audit --no-deps --disable-pip -r /tmp/runtime-reqs.txt

cd web && npm ci && npm audit
cd ../tools/build-mcpb && npm ci && npm audit
```
