---
id: SPEC-103
title: Knowledge-graph parser
phase: 1
depends_on: [SPEC-004, SPEC-102]
model: sonnet-5
effort: high
status: draft
---

# SPEC-103: Knowledge-graph parser

## Goal
Implement `docs/vault-format.md` v1 exactly: markdown in → typed model out
(entity, frontmatter, observations, relations, wikilinks, per-model variants,
sub-note permalinks). The golden corpus from SPEC-004 is the contract.

## Deliverables
1. `palaia_hub.vault.parse` — pure functions (no I/O):
   `parse_note(text, path) -> ParsedNote`; serializer
   `render_note(ParsedNote) -> text` (round-trip stable).
2. Frontmatter normalization per spec (type coercions, BOM, malformed-YAML
   degradation to plain note — never an exception for user content).
3. Forward-reference model: relations to not-yet-existing targets carry the
   target name; resolution happens at index time (SPEC-104), not parse time.
4. Conformance runner: pytest parametrized over
   `docs/vault-format-conformance/` — every golden file asserted against its
   expected-JSON sibling.

## Acceptance criteria
- [ ] 100% of the golden corpus passes (valid parses AND invalid rejections)
- [ ] round-trip: parse→render→parse is a fixed point for every valid corpus file
- [ ] property test: random garbage never raises, always yields a plain note
- [ ] parser is pure (no filesystem/DB imports) — enforced by an import-linter rule
- [ ] p50 parse time < 1ms on corpus-sized notes (guard against regex blowup)

## Non-goals
No indexing, no search, no schema validation (Picoschema-class features are
Phase 2+).

## Model note
Sonnet 5 / high — the design is fully specified; golden tests make correctness
mechanical. Corpus extensions along the way go back through SPEC-004's owner.
