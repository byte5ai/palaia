---
id: SPEC-207
title: Auto-capture & memory-use skills
phase: 2
depends_on: [SPEC-107, SPEC-106]
model: opus-5
effort: high
status: ready
---

# SPEC-207: Auto-capture & memory-use skills

## Goal
Agents that actually USE the memory without being told — via skills, the
provider-portable mechanism (agentskills SKILL.md format, 40+ adopters).

## Deliverables
1. `v3/clients/skills/` — skill packages:
   - `palaia-memory` (core): when to recall (start of task, before deciding,
     on unfamiliar names), how to use `build_context` for continuity, scope
     etiquette, and the capture discipline: what deserves capture (decisions
     + why, conventions, corrections, hard-won gotchas), the 4-field
     contract, search-before-capture, drop-and-move-on (never curate inline).
   - `palaia-capture` (minimal, for constrained agents): capture only.
   Both carry per-model guidance where behavior differs (the format's
   variant concept applied to skill prose).
2. Skill-format validity: agentskills frontmatter lint in CI; plugin-manifest
   wrapper for Claude Code (`.claude-plugin` style) prepared for Phase 3
   marketplace distribution.
3. Connect-a-client page offers the skills per client with install
   instructions (copy-paste or file download), gated to clients that support
   skills.
4. **Effectiveness harness** (the differentiator): scripted transcript tests
   using the sandbox claude CLI against a seeded hub — given a task prompt
   that SHOULD trigger recall and one that SHOULD trigger capture, assert the
   tools actually get called (behind an env flag; excluded from CI, run
   documented in the PR with results).

## Acceptance criteria
- [ ] skills pass format lint; no jargon in user-facing text
- [ ] effectiveness runs documented: recall-trigger and capture-trigger
      prompts both exercised with the real CLI, results honest (misses
      analyzed, prompt iterated at least once)
- [ ] connect-page integration behind client capability flags
- [ ] captures produced in the effectiveness run pass format-spec §7
