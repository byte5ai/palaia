---
id: SPEC-407
title: Phase-4 gate — "two agents on different providers hand off work"
phase: 4
depends_on: [SPEC-401, SPEC-402, SPEC-403, SPEC-404, SPEC-405]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-407: Phase-4 gate evidence

## Goal
Prove the roadmap's Phase-4 exit criterion with SPEC-209/308's evidence
discipline: **two agents on different providers hand off work through
palaia** — a handoff envelope with a vault reference, sent by one, picked
up and acted on by the other.

## Deliverables
1. e2e scenario (extends the SPEC-308 harness): agent A is the real
   `claude` CLI (OAuth, profile `default`) driven by a task prompt; agent B
   is a scripted second-provider-shaped MCP client (`fastmcp.Client` with a
   `plt_` token on a different profile — the sandbox has no codex binary;
   say so, and pin the wire-level equivalence the same way SPEC-209 did).
   A registers, writes its findings to memory, sends a `handoff` with the
   ref; B checks, follows the ref via `recall`/`read`, and completes the
   task using what A learned. Assert on B's real output containing A's
   vault-stored fact — the handoff must carry knowledge, not just bytes.
2. The same scenario's directory half: B found A (or its handoff) via a
   scope query, not a hardcoded handle.
3. A skill-driven variant (env-gated, SPEC-404's harness): agent A gets
   only the task and the skills — no mention of the messenger in the
   prompt — and the run records whether the handoff happened unprompted
   (rate reported honestly; this is evidence, not a hard assert).
4. `v3/docs/client-matrix-results.md` §8: dated "messenger" section —
   per-client evidence or honest "not verified".
5. Draft gate paragraph appended to IMPLEMENTATION.md §6 (marked draft —
   the architect holds the gate); issues filed for quirks, SPEC-209 style.

## Acceptance criteria
- [ ] the two-agents handoff e2e passes and asserts knowledge transfer
      (A's fact in B's output), run twice, no flakes
- [ ] discovery via directory query, not hardcoded handles
- [ ] skill-driven rate documented from ≥3 real runs
- [ ] docs updated with dated evidence; full suite green at the end

## Non-goals
New features; vendor-cloud clients (claude.ai/ChatGPT) — the owner's
phone test remains the standing manual item.
