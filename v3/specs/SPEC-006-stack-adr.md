---
id: SPEC-006
title: Stack ADR write-up
phase: 0
depends_on: []
model: sonnet-5
effort: low
status: ready
---

# SPEC-006: Stack ADR write-up

## Goal
Turn MASTERPLAN §8 into `v3/decisions/004-stack.md` (ADR format per
`decisions/000-template.md`): Python 3.12+/FastMCP 3.x/FastAPI core, TS/React/
Tailwind dashboard, SQLite-only storage, Docker-first packaging; alternatives
(Rust/Go single binary, TS everywhere) with reasons; consequences incl. the
"never pin a beta framework in a release" rule and the FastMCP 4.x adoption
criterion (stable + MCP 2026-07-28 need).

## Acceptance criteria
- [ ] ADR complete per template, status "Proposed" for owner sign-off
- [ ] pin policy stated (FastMCP 3.x now; 4.x when stable)
- [ ] MASTERPLAN §15 decision #1 row updated to link the ADR

## Model note
Sonnet 5 / low — the thinking is done; this is careful transcription.
