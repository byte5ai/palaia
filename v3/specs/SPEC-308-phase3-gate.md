---
id: SPEC-308
title: Phase-3 gate — "install a tool once, every AI has it"
phase: 3
depends_on: [SPEC-301, SPEC-302, SPEC-303, SPEC-304, SPEC-305, SPEC-306]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-308: Phase-3 gate evidence

## Goal
Prove the roadmap's Phase-3 exit criterion end-to-end, honestly, with the
SPEC-209 evidence discipline: **install a tool once (marketplace), and it
is available to every connected AI** — different clients, different
profiles, no per-client setup.

## Deliverables
1. e2e scenario (extends the SPEC-113 harness): curated-index entry →
   dashboard-API install (consent flow included) → the tool answers on TWO
   different profiles through two differently-authenticated real clients:
   the real `claude` CLI (OAuth default path, SPEC-209's machinery) and a
   scripted `fastmcp.Client` with a `plt_` token — one install, two AIs,
   zero client-side tool config.
2. The same scenario through the MCPB proxy (SPEC-306): the stdio path
   sees the newly installed tool without any bundle change.
3. `v3/docs/client-matrix-results.md` updated: a "tools follow the
   profile" column/section with per-client evidence or an honest
   "not verified", SPEC-209 rules unchanged.
4. Gate paragraph appended to IMPLEMENTATION.md §6 draft (the architect
   holds the gate; this SPEC assembles the evidence).
5. Issues filed for every quirk found, SPEC-209 style.

## Acceptance criteria
- [ ] the two-clients-one-install e2e passes in one pytest run (env-gated
      parts skip honestly)
- [ ] the MCPB-proxy variant passes
- [ ] client-matrix doc updated with dated evidence
- [ ] full suite green at the end (this SPEC adds tests, changes no
      behavior; any behavior fix it needs goes through its own issue/PR)

## Non-goals
New features. This SPEC only proves, documents, and files.
