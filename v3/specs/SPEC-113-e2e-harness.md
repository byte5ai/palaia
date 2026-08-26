---
id: SPEC-113
title: E2E harness & golden fixtures
phase: 1
depends_on: [SPEC-102, SPEC-105]
model: sonnet-5
effort: medium
status: draft
---

# SPEC-113: E2E harness & golden fixtures

## Goal
The proof machinery for the Phase-1 exit criterion: scripted end-to-end
scenarios driving the hub exactly like real clients do, plus the shared golden
vault every SPEC's tests build on.

## Deliverables
1. **Golden vault** `v3/tests/fixtures/golden-vault/`: ~60 notes exercising the
   format spec (entities, relations incl. forward refs, per-model variants,
   inbox entries, two-vault setup), with a query battery + expected results.
   *(Note authoring per SPEC-004 corpus style: Sonnet 4 / low sub-task.)*
2. **MCP client simulator**: thin async client speaking streamable HTTP
   (2026-07-28) against the gateway — connect, list tools, call tools, assert;
   usable from pytest.
3. **Scenario suite** (`v3/tests/e2e/`):
   - S1 "two providers, one memory": client A (simulated Claude Code) writes,
     client B (simulated Codex, different token/profile) finds it
   - S2 external edit: file edited on disk → searchable within budget
   - S3 kill/recover: hub killed mid-writes → restart → doctor verify clean
   - S4 rebuild: delete index → reindex → query battery identical
   - S5 fresh-install flow: container up → wizard API → first note (backs the
     SPEC-110 headline scenario)
4. CI wiring: e2e job in v3-ci.yml (compose-based), artifacts on failure
   (logs, vault snapshot).

## Acceptance criteria
- [ ] all five scenarios green in CI on amd64
- [ ] harness fails loudly on tool-schema drift (golden tools/list snapshot)
- [ ] any SPEC can import the simulator + golden vault as pytest fixtures
- [ ] a failing scenario dumps a reproducible bundle (logs + vault + config)

## Non-goals
Real client binaries in CI (manual matrix validation is a Phase-2 package);
load testing.
