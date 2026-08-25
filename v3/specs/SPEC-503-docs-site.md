---
id: SPEC-503
title: Docs site — user documentation for 3.0
phase: 5
depends_on: [SPEC-110, SPEC-304, SPEC-405]
model: sonnet-5
effort: high
status: ready
---

# SPEC-503: Docs site

## Goal
User-facing documentation a non-developer can follow — the reference the
onboarding page (SPEC-504) links into. The repo's `v3/docs/` today is
engineering documentation; this SPEC builds the *user* docs as a static
site, without forking the truth.

## Deliverables
1. `v3/site/docs/`: a static docs site (fixed tooling choice: **Astro
   Starlight** — static output, no server, search built in, MIT; if a
   hard blocker appears, the fallback is VitePress, stated in the PR).
   Structure: Start here (what palaia is, 5-minute install per platform) ·
   Connect your AI (one page per client from the §6 matrix, reusing the
   connect-page snippets as the source of truth — imported/generated, not
   copy-pasted) · Your memory (vault concepts for humans: notes, captures,
   the curator, review) · Marketplace & tools · Profiles & access
   (modes, sign-in, tokens — plain language) · Agents & messages ·
   Automations · Troubleshooting/FAQ · For developers (links into the
   repo's engineering docs + SDK).
2. Single-source rules, enforced not hoped: client snippets and skill
   descriptions are generated from `v3/web/src/lib/clients.ts` /
   `skills.ts` at build time (a small extraction script); a drift test
   fails when the generated pages are stale.
3. Tone & style: jargon-free (the shared blocklist lint runs over the
   prose, code blocks exempt), Lume-derived theme tokens (light/dark),
   every page answers "what do I do" before "how it works".
4. CI: the site builds in the v3 web lane; broken internal links fail the
   build (Starlight's link checker or a script).
5. Screenshots policy: this sandbox cannot produce real product
   screenshots — pages are written screenshot-optional with explicit
   `<!-- screenshot: ... -->` markers and a SHOTLIST.md for the owner;
   never a fabricated image.

## Acceptance criteria
- [ ] site builds clean in CI; internal links verified
- [ ] client pages generated from the real snippet source; drift test red
      when the source changes without regeneration
- [ ] jargon lint green over all prose
- [ ] a "first shared memory" walkthrough exists end-to-end (install →
      connect two AIs → see the same memory in both) — the written twin of
      the Phase-5 exit criterion
- [ ] troubleshooting covers the real quirks from client-matrix-results.md
      (#232's status display, FASTMCP_SSRF_TRUST_PROXY, plan gating)

## Non-goals
Hosting/deployment of the site (owner's DNS/CDN; the build output + a
README suffice); versioned docs for v2; translations.
