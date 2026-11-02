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
| Node, dashboard | `v3/web/package.json` + `package-lock.json` | The lockfile is the pin; CI installs with `npm ci` | Only `react`, `react-dom` and `react-router-dom` reach the built dashboard; everything else is build and test tooling |
| Node, extension tooling | `v3/tools/build-mcpb/package-lock.json` | Same | **Shipped in the runtime image** (issue #594): the image runs the `mcpb` CLI from this tree to build and sign each Claude Desktop extension download, so its whole tree counts as runtime, devDependency or not |
| Node, docs site | `v3/site/docs/package-lock.json` | Same | Static site; nothing from here is in the image or served by a hub |
| Container base | `v3/deploy/Dockerfile` | `python:3.12-slim`, `node:26-slim` | Rebuilt on every release, so a base-image fix arrives with the next image |

**One lockfile per track.** `v3/uv.lock` covers the whole v3 Python workspace
and nothing outside it; v2's dependencies are separate, per `CONTRIBUTING.md`.
`uv lock --check` runs in CI, so a `pyproject.toml` edit that was never
locked fails the build rather than resolving differently on someone else's
machine.

## How auditing runs

| Check | Command | Where |
|---|---|---|
| The lockfile matches the manifests | `uv lock --check` | CI, every pull request and every batch run |
| Python advisories | `pip-audit` against the exported lockfile | CI batch run (advisory job) |
| Node advisories, dashboard | `npm audit` in `v3/web` | CI batch run (advisory job) |
| Node advisories, extension tooling | `npm audit` in `v3/tools/build-mcpb` | CI batch run (advisory job) |
| Node advisories, docs site | `npm audit` in `v3/site/docs` | By hand, at each dependency sweep (not in the CI advisory job yet) |

The batch run is `v3-ci-batch.yml`, dispatched on `main` after a series of
merges and required green before every release.

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

Run on 2026-11-02 (issue #610, from the pre-build review #601), with `npm
audit` against the committed lockfiles. Counts are vulnerable package
entries as `npm audit` reports them, not distinct advisories.

| Target | Before | After | What is left |
|---|---|---|---|
| Python, runtime and dev | No known vulnerabilities | — | — |
| `v3/web` | 20 (8 high, 12 moderate) | **11 moderate** | One advisory, minimatch (below) |
| `v3/site/docs` | 25 (1 critical, 9 high, 15 moderate) | **11 moderate** | The same minimatch advisory |
| `v3/tools/build-mcpb` | 3 high | **2 high** | One advisory, zod (below) |

**Fixed in this pass**, by updating within the declared ranges unless noted:

- Dashboard: `vite` 8.2.2 → 8.3.5 (and Ladle's own `vite` → 6.4.5),
  `vitest`/`@vitest/mocker` → 4.1.12, `undici` 8.10.0 → 8.12.3, `zod` →
  4.6.7, `brace-expansion`, `decode-uri-component`, `source-map-js`,
  `js-yaml`. `jsdom` stays on **30.0.x** (`~30.0.1`): jsdom 30.1 changed the
  Blob internals that vitest 4.1.12's jsdom environment reads
  (`URL.createObjectURL` → `makeCompatBlob` → `_buffer`), which broke 18
  dashboard tests; 30.0.1 already takes the patched `undici`. Lift the pin
  together with the vitest version that supports jsdom 30.1.
- Docs site: `astro` 7.2.7 → 7.4.4 (floor raised to `^7.4.4`): remote code
  execution through AVIF image optimization (GHSA-26w7-cxv4-gfx2, critical),
  XSS through unescaped `<script>`/`<style>` content (GHSA-98hj-9722-w3j8)
  and CSS injection in View Transitions (GHSA-mpr7-6m5w-76rw).
  `@astrojs/markdown-remark` moves its exact pin 7.2.4 → 7.3.5 with it:
  `astro.config.mjs` imports `unified` from it, so it has to be the version
  Astro itself uses (Astro 7.4 needs `^7.3.0`). Plus `sharp` 0.35.5, `devalue`
  6.0.3, `vite` 8.3.5, `fast-uri` 3.1.9, `undici`, `zod`, `js-yaml`,
  `source-map-js`, `brace-expansion`. All 30 built pages have the same text as
  before; the build now logs two Astro content notices (no `i18n`
  collection, no custom 404 entry) that change nothing in the output.
- Extension tooling: `node-forge` 1.4.0 → 1.4.2 (twelve advisories, among
  them RSA signature verification accepting extra data, GHSA-86w9-cpqp-85rv).
  The signing path still works: the build signs the bundle, and the hub's
  builder tests run `mcpb validate`, `pack` and `sign` with the real CLI.

### Open: minimatch, GHSA-g3hv-75wg-m249 (moderate) — dashboard and docs site

Denial of service through glob-part amplification for an attacker-controlled
pattern; fixed only in `minimatch` 11.0.1 (published 2026-10-30). All 11
entries in each project are this one advisory, reached through the lint and
type-generation tooling:

- `eslint` 10.14.0 and `@eslint/config-array` → `minimatch` 10.2.6;
  `typescript-eslint` 8.72.1 → `@typescript-eslint/typescript-estree` →
  `minimatch` 10.2.6 (both projects);
- dashboard only: `openapi-typescript` 7.13.0 → `@redocly/openapi-core`
  1.34.22 → `minimatch` 5.1.9.

These are the newest releases, and each still requires `minimatch` below 11
(`openapi-typescript` requires `@redocly/openapi-core` ^1.34). The patterns
they match come from this repository's own ESLint, TypeScript and OpenAPI
configuration, at development time; none of it is in the dashboard bundle, the
image or the docs site's output. No override: forcing `minimatch` 11 under
ESLint would put an untested major beneath the tool that decides which files
get linted. **Recheck** when ESLint, typescript-eslint or openapi-typescript
take `minimatch` ≥ 11.0.1, or at the next sweep.

### Open: zod, GHSA-mrhx-c7xc-m3w5 (high) — extension tooling

Memory exhaustion when an unbounded array schema validates a large
attacker-supplied array; fixed only in `zod` 4.6.6. `@anthropic-ai/mcpb` 2.1.2
(the newest release) requires `zod` ^3.25.67 (resolved 3.25.76), and zod 4 is
a different API for it and for `zod-to-json-schema` 3, so there is nothing to
update to and no safe override.

This tree is in the runtime image, so where it runs matters: the hub runs
`mcpb validate`, `pack` and `sign` (`palaia_hub/mcpb/builder.py`) on a
manifest made from palaia's own template plus scalar values from the request
(version, hub address, tool set, issuer, access key). No request supplies an
array, and the download route lives under `/api` on the private dashboard
address, which the cloud entry never forwards. **Recheck** when
`@anthropic-ai/mcpb` moves to a fixed zod.

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
cd ../../site/docs && npm ci && npm audit
```
