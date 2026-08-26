---
id: SPEC-002
title: "Spike: FastMCP gateway proof"
phase: 0
depends_on: []
model: sonnet-5
effort: high
status: ready
---

# SPEC-002: Spike — FastMCP gateway proof

## Goal
Prove (or refute) the riskiest gateway assumptions from MASTERPLAN §5.2 with
running code, before Phase 1 commits to them. A spike: the code is throwaway,
the **findings report is the deliverable**.

## Questions to answer
1. Can FastMCP 3.x mount two servers (one local in-process, one remote via
   ProxyProvider) behind ONE streamable-HTTP endpoint with namespaced tools?
2. Do per-path profiles work (`/mcp/full` vs `/mcp/memory-only` exposing
   different tool subsets of the same mounts)?
3. Does static bearer-token auth per profile work, and what does FastMCP's
   auth layer need for the later OAuth upgrade (CIMD support present)?
4. Do tool renames/aliases survive the mount (rename a mounted tool, verify a
   client sees only the new name)?
5. Does Claude Code (`claude mcp add --transport http`) connect and call tools
   through the gateway end-to-end? Document any handshake/version quirks
   (v1 vs v2 runtime, MCP 2026-07-28 statelessness).

## Deliverables
- `v3/spikes/gateway/` — runnable spike (excluded from CI quality gates)
- `v3/spikes/gateway/FINDINGS.md` — per question: answer, evidence (commands +
  output), surprises, and a "what this changes for SPEC-105/108" section

## Acceptance criteria
- [ ] all five questions answered with reproducible evidence
- [ ] FINDINGS.md names concrete FastMCP APIs/versions used
- [ ] one end-to-end transcript: Claude Code → gateway → mounted tool → response
- [ ] explicit list of assumptions that did NOT hold (empty list is suspicious)

## Non-goals
No production code quality, no OAuth, no persistence.

## Execution notes
Read MASTERPLAN §5.2 + research/mcp-landscape-2026.md §1/§5 first.
Fable 5 reads FINDINGS.md at the phase gate.
