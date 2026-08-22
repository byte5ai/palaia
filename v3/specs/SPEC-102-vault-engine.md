---
id: SPEC-102
title: Vault engine (files, atomicity, watcher, git)
phase: 1
depends_on: [SPEC-003, SPEC-004, SPEC-101]
model: opus-5
effort: high
status: draft
---

# SPEC-102: Vault engine — files, atomicity, watcher, git

## Goal
The heart of palaia: vault CRUD where **files are the only truth**
(MASTERPLAN §5.1). Normative input: `docs/vault-format.md` v1 (SPEC-004) and
the SPEC-003 findings. Correctness beats features here.

## Deliverables
1. `palaia_hub.vault` — vault registry (multiple vaults, each: name, purpose,
   path, isolated storage) + per-vault engine with:
   - `write_note / read_note / edit_note / move_note / delete_note / list_dir`
   - `rename_entity`: renames a note's identity and rewrites all inbound
     wikilinks/backlinks vault-wide in ONE atomic git commit (format-spec rename
     semantics)
   - **synchronous write-through**: the call returns only after the file is on
     disk (fsync) — no accepted-but-unwritten states (explicit anti-goal:
     basic-memory's async materialization wart)
   - atomic writes (tmp + fsync + rename), stable permalinks per format spec
2. **Watcher**: watchfiles-based, debounced per SPEC-003 findings, detects
   external create/edit/move/delete (checksum-based move detection), emits
   typed change events on an internal bus stub (full bus is Phase 2 — define
   the event dataclasses now).
3. **Git layer**: auto-commit per logical write with attributed message
   (`agent/client/origin: summary`); batching strategy per SPEC-003 findings;
   repo auto-init; external edits picked up as their own commits on next write;
   `vault history <permalink>` API.
4. Doctor primitives: `verify()` (file↔index consistency check interface — the
   index side lands in SPEC-104) and `reindex()` hook points.

## Acceptance criteria
- [ ] kill -9 mid-write-burst (test harness): no corrupt files, no lost
      acknowledged writes, vault opens clean
- [ ] concurrent writers (async tasks) to different notes: no interleaving
      corruption; same note: second writer gets a checksum-conflict error
- [ ] external edit → change event within the debounce budget (integration test)
- [ ] move detection: rename on disk preserves permalink identity
- [ ] `rename_entity` on the golden vault: zero dangling backlinks afterward,
      exactly one commit, external (Obsidian) partial renames flagged by doctor
- [ ] every acknowledged write is a git commit with correct attribution
- [ ] two vaults never share files, SQLite, or git state (isolation test)
- [ ] 10k-note vault: write p50 within SPEC-003's measured budget ±20%

## Non-goals
Parsing note *semantics* (103), indexing/search (104), MCP exposure (105).

## Model note
**Opus 5 / high**, plus **Fable 5 review** before merge — atomicity, watcher
races and git integration are exactly where subtle bugs cost user data.
