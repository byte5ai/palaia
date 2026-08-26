---
id: SPEC-003
title: "Spike: vault engine round-trip proof"
phase: 0
depends_on: []
model: sonnet-5
effort: high
status: ready
---

# SPEC-003: Spike — vault engine round-trip proof

## Goal
Prove the files-as-truth architecture (MASTERPLAN §5.1) end to end on a toy
scale before SPEC-102 builds it properly. Findings report is the deliverable.

## Questions to answer
1. Round-trip: write markdown notes (frontmatter + observations + wikilinks) →
   parse → index into SQLite (FTS5) → search → delete the DB → rebuild from
   files → identical search results?
2. External-edit loop: modify a note on disk (simulating Obsidian), does the
   watcher (watchfiles) pick it up and reindex within ~2s? What debounce is
   sane? What happens with a rapid rename+edit?
3. Git layer: auto-commit per write with attributed messages — measure cost per
   commit at 1k/10k notes (pygit2 vs subprocess git); does `git status`
   stay fast? Is one-commit-per-write viable or is batching needed?
4. Vector search: fastembed + sqlite-vec on the same toy vault — cold-start
   time, per-note embed cost, hybrid merge sketch.
5. Atomicity: kill -9 during a write burst — is the vault ever corrupt? Is the
   index always rebuildable afterward?

## Deliverables
- `v3/spikes/vault/` — runnable spike + a generator for a 10k-note toy vault
- `v3/spikes/vault/FINDINGS.md` — per question: answer, numbers, surprises,
  and "what this changes for SPEC-102/103/104"

## Acceptance criteria
- [ ] all five questions answered with numbers (timings, sizes), not adjectives
- [ ] rebuild-from-files proven byte-identical in search behavior
- [ ] kill-test performed and documented (commands included)
- [ ] git cost table at 1k/10k notes present

## Non-goals
No production quality, no full grammar (SPEC-004 defines it), no recall logic.

## Execution notes
Read MASTERPLAN §5.1 + research/basic-memory.md §2 first.
