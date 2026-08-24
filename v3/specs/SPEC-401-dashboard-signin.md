---
id: SPEC-401
title: Dashboard sign-in — the admin session gate
phase: 4
depends_on: [SPEC-203, SPEC-204, SPEC-205]
model: opus-5
effort: medium
status: ready
---

# SPEC-401: Dashboard sign-in

## Goal
Close issue #242: the admin surface (`/api/*`, the dashboard) gets an owner
session, which is what the masterplan's mode table requires before a public
dashboard may exist — and what lifts the temporary "mode 'open' is refused"
guard.

## Deliverables
1. **One door, reused** (MASTERPLAN §5.5): the dashboard session IS the
   SPEC-203/204 login session (`palaia_oauth_session`) — password or IdP,
   whichever the hub is configured for. No second account system, no second
   cookie for the same identity.
2. Enforcement middleware on the admin surface: every `/api/*` route
   requires a live owner session **when enabled**, except a fixed
   allowlist that must work logged-out (`/api/health`, `/api/info`, the
   OAuth/IdP endpoints themselves, and the SSE events stream carries no
   secrets? — no: events REQUIRE the session; only health/info/sign-in
   stay open). `/mcp/*` is untouched (its own token/OAuth auth, SPEC-108/
   203). The dashboard SPA redirects to the sign-in page when a 401 comes
   back; the sign-in page reuses SPEC-203's (extended, not duplicated).
3. **CSRF for the REST surface**: state-changing methods (POST/PUT/PATCH/
   DELETE) under `/api/*` require the double-submit token the login flow
   already set (SPEC-203's pattern) via an `X-Palaia-CSRF` header; the SPA's
   API client sends it on every call. GET stays CSRF-free.
4. Mode policy: enforcement is **mandatory in `open` mode** and **on by
   default in `cloud`** (the dashboard is VPN-only there, but defense in
   depth is cheap); in `locked` it is opt-in (`dashboard.require_sign_in`,
   default false — a LAN hub must keep its zero-config first-run wizard,
   which is also why enforcement only activates once an owner account or
   IdP exists; the wizard's first run creates one as its first step in
   enforcing modes).
5. Lift the #242 guard: `load_config` and the mode endpoint accept `open`
   again **iff** sign-in is configured; the refusal message stays for an
   open-mode config with no owner account/IdP. Restore the open-mode
   entry-point tests to their pre-guard shape plus the new conditions.
6. Session UX: sign-out button in the shell; session TTL from
   `oauth.session_ttl`; the SPA handles expiry mid-use gracefully (one
   redirect, no lost form state beyond the page).

## Acceptance criteria
- [ ] with enforcement on: every non-allowlisted `/api/*` route 401s
      without a session (parametrized walk over the app's real route table,
      so a new route cannot ship unguarded by accident) and works with one
- [ ] state-changing call without the CSRF header 403s; the SPA client
      sends it (vitest on the api client)
- [ ] `open` mode: accepted with sign-in configured (e2e: public-style
      bind + login + one admin call), still refused without
- [ ] `locked` zero-config first run: wizard reachable without any session
      (regression on SPEC-110's flow)
- [ ] MCP endpoints unaffected (existing e2e stays green)
- [ ] jargon-free copy on the sign-in redirects (lint)

## Non-goals
Multi-user accounts/roles; remember-me beyond the session TTL; rate
limiting (SPEC-205's middleware already covers auth paths in cloud/open).
