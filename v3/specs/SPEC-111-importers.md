---
id: SPEC-111
title: "Importers: palaia v2 and basic-memory"
phase: 1
depends_on: [SPEC-102]
model: sonnet-5
effort: medium
status: draft
---

# SPEC-111: Importers — palaia v2 and basic-memory

## Goal
Nobody starts from zero: read a palaia v2 store or a basic-memory vault and
write format-spec-valid v3 vault entries with preserved metadata. (Reading a
user's own files has no license implications — ADR-002.)

## Deliverables
1. `palaia-hub import v2 <path>`: reads a v2 `.palaia/` store (SQLite backend
   AND legacy tier directories hot/warm/cold), maps entries (type, scope, tags,
   timestamps, body) to v3 notes; tier → decay-score seed; provenance noted.
2. `palaia-hub import basic-memory <path>`: maps their frontmatter/observations/
   relations to ours per a documented mapping table (`docs/import-mappings.md`);
   unknown custom keys preserved as metadata.
3. **Cold-embed as a visible background job:** embedding an imported vault takes
   minutes to hours at realistic sizes (spike: ~437 ms/note) — imports must
   complete and be FTS-searchable immediately, with vector embedding running as
   a progress-visible background job (dashboard + `inbox_status`-style API).
4. Dry-run mode (report what would be created, collisions, unmappable items);
   idempotent re-run (stable IDs, no duplicates); import runs into a dedicated
   folder + git commit series for easy review/rollback.
5. Golden fixtures: a frozen mini v2 store and mini basic-memory vault under
   `v3/tests/fixtures/` with expected v3 output checked in.
   *(Fixture creation is a good Sonnet 4 / low sub-task.)*

## Acceptance criteria
- [ ] golden fixtures round-trip byte-stable (expected output committed)
- [ ] re-running an import creates zero new notes (idempotence test)
- [ ] dry-run report lists counts + every unmappable item with a reason
- [ ] imported notes pass the SPEC-103 conformance parser without warnings
- [ ] tier/decay seeding documented and tested

## Non-goals
Live sync with either source; importing Claude/ChatGPT exports (later, own spec).
