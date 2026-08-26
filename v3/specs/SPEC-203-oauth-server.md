---
id: SPEC-203
title: OAuth 2.1 authorization server
phase: 2
depends_on: [SPEC-108]
model: opus-5
effort: high
status: ready
---

# SPEC-203: OAuth 2.1 authorization server

## Goal
The Phase-2 identity core: palaia as authorization server + resource server so
claude.ai, ChatGPT and mobile apps connect as remote connectors. Design is
MASTERPLAN §5.5 — every mcp-hub production lesson is a REQUIREMENT here, not
advice. **Fable security review is mandatory before merge.**

## Deliverables
1. **Endpoints**: `/.well-known/oauth-authorization-server`,
   `/.well-known/oauth-protected-resource/<profile>` (one per mounted MCP
   profile), `/authorize`, `/token`, `/revoke`, `/register` (DCR fallback),
   `/login` (local admin account this SPEC; IdPs are SPEC-204). Authorization
   Code + PKCE (S256) for interactive clients; `client_credentials` for
   machine clients (admin-provisioned only, no refresh tokens).
2. **Client registration**: CIMD-first (validate client-id metadata documents,
   SSRF-safe fetch), RFC 7591 DCR as legacy fallback; **registered-client GC**
   (interactive clients with no live refresh token, TTL-pruned, throttled).
3. **Tokens**: short-lived access JWTs (Ed25519, `aud` = the profile resource,
   resolved — never minted verbatim from the client's RFC 8707 `resource`;
   tolerate trailing `/mcp` and slashes); **grace-windowed refresh rotation**
   (spent token pinned to its successor for a configurable window, default
   120s — the multi-device fan-out lesson); revocation.
4. **Verification**: resource side stays the SPEC-108 seam — profiles get a
   JWT verifier (fastmcp `JWTVerifier` against the published public key), and
   the SPEC-108 `plt_` tokens keep working in parallel (both verifiers
   accepted per profile) so existing setups don't break.
5. **Store**: hub-level SQLite with explicit connection/locking discipline —
   a concurrency regression test simulating the 6-connector refresh fan-out
   (the mcp-hub daily-re-login incident) is REQUIRED.
6. Mode integration: `cloud`/`open` accept OAuth as satisfying the auth
   mandate; startup summary states which auth methods each profile serves.

## Acceptance criteria
- [ ] scripted OAuth client completes discovery → CIMD/DCR → PKCE code flow →
      token → authenticated MCP call end-to-end (e2e test)
- [ ] two concurrent refreshes of one grant converge (no invalid_grant chain
      teardown); after the grace window the spent token is dead
- [ ] token for profile A rejected by profile B (aud isolation e2e)
- [ ] resource indicator `<issuer>/<name>/mcp` resolves to `<issuer>/<name>`
- [ ] concurrency fan-out test: no 500s, no store corruption
- [ ] orphan DCR clients pruned; machine clients never pruned
- [ ] no secret/token/code ever logged (redaction tests incl. authorize/token
      request logging paths)
- [ ] keys/state files 0600; access tokens never persisted

## Non-goals
GitHub/Google/OIDC login (SPEC-204), exposure wizard (SPEC-205), consent
screens beyond the single-owner login.
