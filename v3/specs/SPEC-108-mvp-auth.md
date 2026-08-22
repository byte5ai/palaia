---
id: SPEC-108
title: "MVP auth: per-client tokens + profiles"
phase: 1
depends_on: [SPEC-101, SPEC-105]
model: sonnet-5
effort: high
status: draft
---

# SPEC-108: MVP auth — per-client tokens + profiles

## Goal
Phase-1 auth without the OAuth server (that's Phase 2): named per-client
bearer tokens, scoped to profiles and vault permissions, with the operating-
mode policy enforced in code from day one (MASTERPLAN §5.5).

## Deliverables
1. Token store: named clients (e.g. "Codex on devbox"), token = high-entropy
   secret, stored **hashed** (argon2id); create/revoke via REST + CLI;
   plaintext shown exactly once at creation.
2. Scopes: per vault `read`/`write` + profile binding; gateway enforces
   per-tool (write tool + read-only token → clean MCP error, not a crash).
3. **Operating-mode enforcement**: `locked` → auth optional (config flag,
   default on), binds per config; `cloud`/`open` → hub **refuses to start** MCP
   endpoints without auth enabled; admin API refuses non-VPN binding in cloud
   mode. Mode transitions validated with actionable errors.
4. Auth middleware ordering + redaction: tokens never logged (SPEC-101 filter
   covers auth paths — test it).

## Acceptance criteria
- [ ] wrong/absent token → 401 with RFC-compliant `WWW-Authenticate`; valid
      token bound to profile A cannot list/call profile B's tools
- [ ] read-scoped token calling a write tool → MCP error naming the missing scope
- [ ] `cloud` mode with auth disabled → startup fails with the exact fix in the
      message
- [ ] token hashes only in storage (test greps the store); rotation works
      (create new, revoke old, old fails immediately)
- [ ] timing-safe comparison used (constant-time verify)

## Non-goals
OAuth/CIMD/IdP login (Phase 2), tunnels/exposure wizard (Phase 2).

## Model note
Sonnet 5 / high, **Fable 5 review mandatory before merge** (security surface).
The design intentionally leaves an upgrade seam for the Phase-2 OAuth AS: the
verifier interface must accept future JWT verification without touching tools.
