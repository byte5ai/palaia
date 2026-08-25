---
id: SPEC-506
title: Phase-5 gate — release candidate + unaided-install evidence
phase: 5
depends_on: [SPEC-501, SPEC-502, SPEC-503, SPEC-504, SPEC-505]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-506: Phase-5 gate evidence

## Goal
Assemble the 3.0 release candidate and the evidence for the exit criterion
— **"a non-developer completes install → first shared memory unaided"** —
with the standing honesty rules. The literal criterion needs a real person
the sandbox does not have; this SPEC delivers everything scriptable plus
the exact protocol for that human test, so the owner can run it in an
evening.

## Deliverables
1. Release engineering: version 3.0.0-rc1 (server, web, sdk, mcpb bundle,
   compose, store packages all agreeing — one VERSION source, a drift
   test), CHANGELOG.md for v3 (generated from the merged PR titles,
   curated by hand into user-language), release workflow dry-run.
2. Scripted gate evidence, extending the SPEC-308/407 harness:
   - the full funnel e2e on the rc image build: fresh home → wizard →
     vault → connect client A (real `claude` CLI, OAuth default path) →
     first memory → connect client B (plt_ scripted) → B recalls A's
     memory — the exit criterion's mechanical twin, one run timed against
     the §13 target (<5 min machine time, report the real number);
   - docker one-liner smoke: the shipped one-liner starts the rc image and
     serves the wizard (env-gated on docker; skipped honestly otherwise —
     state which parts then rest on SPEC-112's existing evidence).
3. `v3/docs/usability-test-protocol.md`: the owner's script for the real
   non-developer session — tasks (install per onboarding page, connect
   your AI, save and retrieve one memory from a second AI), what to
   observe, what counts as "unaided", where to file findings. One page,
   ready to hand to a test person.
4. Docs/evidence updates: client-matrix-results.md §9 (rc validation, dated),
   draft gate paragraph in IMPLEMENTATION.md §6 (marked draft — the
   architect holds the gate), issues for quirks.
5. Release checklist `v3/RELEASING.md`: the ordered list from "gate held"
   to "3.0.0 tag + store submissions + site deploy" with owner-action
   items clearly marked.

## Acceptance criteria
- [ ] version/changelog drift test green; every artifact reports 3.0.0-rc1
- [ ] funnel e2e green twice, timed, number reported honestly
- [ ] one-liner smoke green or honestly env-skipped with the fallback
      evidence named
- [ ] usability protocol reviewed against the onboarding page (every step
      it asks of the tester exists)
- [ ] full suite green at the end; no behavior changes outside release
      plumbing (fixes → issues, SPEC-209 style)

## Non-goals
The human usability session itself (owner runs it); the 3.0.0 final tag
(after the external security review and the human test — RELEASING.md
sequences it); store submissions (owner, per SPEC-501's SUBMIT.md).
