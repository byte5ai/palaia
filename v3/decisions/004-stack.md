# ADR-004: v3 stack — Python core + FastMCP, TypeScript dashboard, SQLite, Docker-first

- **Status:** Accepted
- **Date:** 2026-08-22
- **Deciders:** cwendler

## Context

palaia v3 needs a hub/core stack, a dashboard stack, a storage layer, and a
packaging story. The core must implement an MCP gateway (aggregation,
per-client visibility, per-component auth) and a local-embedding-backed vault
index; the dashboard is a first-run wizard, connector explorer, and status UI
served by the hub. MASTERPLAN §8 lays out the recommendation and the
alternatives considered; this ADR formalizes that decision, records the
adversarial review it survived, and verifies the licensing claim the
masterplan flagged as needing confirmation.

## Decision

- **Hub/core: Python 3.12+** with **FastMCP 3.x** (GA since 2026-02, PrefectHQ):
  its ProxyProvider (remote upstreams), FastMCPProvider (mounting/composition),
  Namespace + per-user Visibility transforms, per-component auth (incl. CIMD),
  and SkillsProvider map 1:1 onto the gateway design — the gateway is largely
  assembly, not invention. **FastAPI** serves the dashboard/REST API.
  Rationale: the MCP ecosystem's center of gravity is Python; local-embedding
  libraries are Python; the team's v2 experience is Python.
- **Dashboard: TypeScript + React + Tailwind**, built to static assets and
  served by the hub — one process, one container. (Team has TS experience from
  the v2 OpenClaw plugin.)
- **Storage: SQLite** (FTS5 + vector extension) as the only database — an
  index, not a source of truth. No Postgres in v3 core.
- **Packaging: single OCI container** for the MVP (`docker run … palaia`),
  compose file, one-line installer; add-on containers arrive with the
  marketplace phase; appliance/app-store images at launch.

## Alternatives considered

- **Rust or Go single-binary core** — best raw install story and performance,
  but slower to build, thinner MCP/embedding ecosystems, and it would forfeit
  the Python velocity this scope needs. Escape hatch: hot paths can move into
  a native extension later; the architecture keeps that door open.
- **TypeScript everywhere** — a stronger contender than it first looks: the
  two hub prior-art projects are TS, the official TS SDK v2 is stable on MCP
  2026-07-28, and Node is unavoidable at palaia's edges anyway (dashboard, the
  MCPB proxy runs in Claude Desktop's bundled Node, MCP Apps). Rejected
  because the TS ecosystem has **no high-level gateway framework** (the
  official SDK is low-level; FastMCP-TS trails the spec and lacks
  proxy/composition) and the local-embedding stack is thinner
  (community-maintained fastembed-js vs. Qdrant-maintained fastembed) —
  choosing TS would mean hand-building exactly the two hardest parts of the
  product.

## Adversarial review (2026-08-22)

The recommendation was re-examined against current sources; it stands, with
one risk added. **FastMCP dependency risk:** the framework is owned by
PrefectHQ, whose commercial Horizon product overlaps palaia's category — OSS
priorities could drift. Mitigations:

1. Permissive license (verified below).
2. The official `python-sdk` as fallback.
3. **All gateway logic sits behind palaia's own interface seam** (SPEC-105) so
   a framework swap never touches tool definitions.
4. The standing rule of never pinning beta releases (below).

The decisive factors for Python remain gateway-framework maturity and the
embedding ecosystem — both verified, not assumed.

## License verification

Checked directly against the upstream repository, 2026-08-22:
[github.com/PrefectHQ/fastmcp](https://github.com/PrefectHQ/fastmcp) is
licensed **Apache License 2.0** (LICENSE file present at repo root; license
badge on the repo page reads "Apache-2.0 license"). Apache-2.0 is permissive
and imposes no copyleft or network-use obligations on palaia — it is
compatible with palaia v3's MIT licensing (ADR-002) and carries no dependency
risk beyond the ordinary maintenance risk named above.

## Consequences

- Pin policy: **FastMCP 3.x now.** Adopt **FastMCP 4.x** only once (a) it is
  out of beta/stable, and (b) it is needed for native MCP 2026-07-28 support.
  **Never pin a beta framework in a release build** — this is the same
  mistake that hurt basic-memory, and it is a standing rule for this project,
  not a one-off judgment call for this dependency.
- Because gateway logic is isolated behind palaia's own interface seam
  (SPEC-105), a future framework swap (e.g. away from FastMCP, or to the raw
  `python-sdk`) is a contained migration, not a rewrite.
- Local-embedding and MCP tooling stay in the Python ecosystem; the dashboard
  stays in TypeScript/React/Tailwind, built once to static assets and served
  by the same container as the hub — no second runtime to deploy.
- SQLite-only storage means no Postgres operational burden for the MVP; if a
  future phase needs multi-writer concurrency beyond SQLite's model, that is
  a new ADR, not a silent scope change.
- Packaging stays single-container through the MVP; add-on containers and
  appliance images are deferred to their respective roadmap phases (§12).
