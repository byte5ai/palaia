---
id: SPEC-504
title: Onboarding page + first-run funnel polish
phase: 5
depends_on: [SPEC-503, SPEC-501, SPEC-110]
model: sonnet-5
effort: high
status: ready
---

# SPEC-504: Onboarding

## Goal
MASTERPLAN §9.3: the palaia.byte5.ai successor — pick your platform, paste
one thing, running in minutes — plus the first-run funnel behind it,
because the Phase-5 exit criterion ("a non-developer completes install →
first shared memory unaided") is won or lost in this funnel, not on the
landing page.

## Deliverables
1. `v3/site/onboarding/`: one static page (same toolchain/theme as
   SPEC-503's site, shared tokens): platform picker (Docker one-liner,
   Compose, Umbrel/CasaOS/Runtipi/TrueNAS via SPEC-501's packages) → the
   ONE thing to paste/click for that platform → "then open
   http://palaia.local (or http://<host>:8420)" → the wizard takes over.
   Copy-to-clipboard, no horizontal scroll on phones, jargon-free.
2. First-run funnel audit, fixed in the product (this is the substance):
   walk the real wizard as a first-timer and close every friction point
   found — target shape: create vault → (mode stays Locked by default) →
   connect first client (snippet/bundle) → write first memory from the
   client → the dashboard celebrates the first memory ("it worked"
   moment). Every error message on the funnel path gets the
   name-the-fix treatment. Document each change honestly in the PR;
   larger redesigns become filed issues, not scope creep.
3. Funnel instrumentation, local-only (§13's time-to-first-memory metric):
   the hub records wizard-step timestamps and time-to-first-memory into a
   local stats store; shown on the dashboard's hub-status ("set up in
   4m12s"); NEVER transmitted anywhere (state this in code and docs —
   privacy principle §10).
4. The wizard's final step links the exact next actions: connect a second
   AI (that's the whole point), install a tool, read the docs (SPEC-503
   deep links).

## Acceptance criteria
- [ ] onboarding page builds in CI, links resolve, snippets match the real
      compose/one-liner (drift test against v3/deploy sources)
- [ ] a scripted first-run walk (API-level: fresh home → wizard endpoints →
      vault → token → first memory write) completes without any step that
      requires editing a file or a shell beyond the install one-liner
- [ ] time-to-first-memory recorded locally and shown; a test proves no
      network egress from the stats path
- [ ] error-message audit: every funnel-path error names its fix (test
      walks the failure branches)
- [ ] jargon lint green; phone-width rendering verified in the component
      tests

## Non-goals
Hosting/DNS (owner); marketing copy beyond the functional page; the real
non-developer usability session itself (SPEC-505 gate protocol — a human
does that).
