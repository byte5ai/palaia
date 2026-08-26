---
id: SPEC-402
title: Session directory — agents become visible
phase: 4
depends_on: [SPEC-105, SPEC-201]
model: sonnet-5
effort: high
status: ready
---

# SPEC-402: Session directory

## Goal
MASTERPLAN §5.4's first half: sessions register with real context (scope,
host, platform, agent kind, model, capabilities), heartbeat with TTL, age
out visibly — the discovery layer the messenger (SPEC-403) addresses into.

## Deliverables
1. `palaia_hub.directory`: SQLite-backed session registry under the hub
   home. A session row (fixed shape): `handle` (server-minted, stable for
   the registration's lifetime, URL-safe), `scope` (free text, e.g.
   "refactoring the billing service in repo X"), `host`, `platform`
   (claude-code | claude-desktop | claude-ai | codex | gemini | other —
   open enum, stored verbatim), `agent_kind`, `model` (verbatim string the
   agent self-reports; never trusted for anything but display), `status`
   (`active` | `idle` | `stale`), `capabilities` (list of free-text tags),
   `registered_at`, `last_seen_at`, `ttl_seconds`.
2. Lifecycle: `register` returns the handle + a **session secret** (needed
   for subsequent heartbeat/update/deregister — another session must not be
   able to impersonate or evict a peer; stored hashed, SPEC-203's
   secrets_util pattern). `heartbeat` bumps `last_seen_at`; a session past
   its TTL turns `stale` (visible, not deleted); past 5×TTL it is pruned.
   Status `idle` is self-reported; `stale` is always computed server-side.
3. MCP tool family `directory_*` on gateway profiles (opt-in per profile
   like stash): `directory_register`, `directory_heartbeat`,
   `directory_update` (scope/status/capabilities), `directory_list`
   (filterable by status/platform/capability), `directory_query` (scope
   substring/role query — "who is working on repo X"), `directory_deregister`.
   Dual output (structured + text), IDENTITY line distinguishes it from
   memory/stash, alias absorption per house style.
4. REST mirror `/api/directory` (list/query only — mutations come from the
   sessions themselves via MCP) for the dashboard; SPEC-405 builds the
   screen.
5. Events (additive): `session.registered`, `session.updated`,
   `session.idle`, `session.stale`, `session.deregistered` — the masterplan
   names `session.*` in the §5.6 vocabulary; automations (SPEC-307) can
   trigger on them.
6. Scopes: `directory:read`/`directory:write` enforced per-tool
   (SPEC-108 pattern); golden tools snapshot regenerated via the
   documented command.

## Acceptance criteria
- [ ] register → list round-trip through a real `fastmcp.Client`; handle
      stable across heartbeats
- [ ] a wrong session secret cannot heartbeat/update/deregister another
      session (impersonation test)
- [ ] TTL: expired session shows `stale` (clock-injectable), pruned at 5×TTL
- [ ] query by scope substring and by capability both filter correctly
- [ ] events fire on register/stale/deregister (bus test)
- [ ] read-scoped token cannot register (per-tool scope test)

## Non-goals
Message delivery (SPEC-403); the dashboard screen (SPEC-405); any
cross-hub federation.
