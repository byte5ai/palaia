---
id: SPEC-204
title: Identity-provider sign-in (GitHub / generic OIDC)
phase: 2
depends_on: [SPEC-203]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-204: IdP sign-in

## Goal
The AS's `/login` learns real identity providers, with the mcp-hub rules.

## Deliverables
1. GitHub OAuth sign-in: zero scopes requested, provider token read once for
   the username then **discarded**, case-folded allow-list of permitted users;
   CSRF state stored server-side, single-use, ticket never in the URL.
2. Generic OIDC provider (discovery-configured) with the same discipline.
3. **One-door rule enforced in code**: when an IdP is configured, the local
   password route is NOT registered.
4. Dashboard settings section (plain-language copy per the jargon rule:
   "Sign in with GitHub", never "OIDC").

## Acceptance criteria
- [ ] full GitHub-shaped flow against a mocked provider (ticket single-use,
      state mismatch rejected, non-allow-listed user rejected)
- [ ] provider token provably not persisted (store scan test)
- [ ] IdP configured → password endpoint absent (404, not 403)
- [ ] UI copy passes the jargon lint (no protocol acronyms user-facing)
