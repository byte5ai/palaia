# ADR-003: Vault format v1 — what we adopted, changed, and rejected

- **Status:** Accepted (owner sign-off 2026-08-22)
- **Date:** 2026-08-22
- **Deciders:** cwendler (sign-off), design per SPEC-004

## Context

The vault format is v3's most consequential design artifact: every note ever
written conforms to it, and basic-memory's history shows what an unspecified
grammar costs (regex heuristics patched for years — checkboxes, callouts,
timestamps, all discovered in production). Inputs: the 18-dimension comparison
(`research/memory-design-comparison.md`), spike findings (SPEC-002/003), owner
requirements (stable identity, referenced values, inbox contract, per-model
recall), and ADR-002's clean-room rule.

## Decision

`docs/vault-format.md` v1 is the normative format. Load-bearing choices:

1. **Adopted from basic-memory (clean-room):** entity/observation/relation
   grammar in plain Markdown, wikilink relations with forward references,
   permalink identity, `memory://` addressing with sub-note synthetic
   permalinks, warn-first parsing, Obsidian coexistence.
2. **Formalized where bm accreted:** the grammar is EBNF with a closed
   exclusion list (E1–E7) and a closed warning-code list, contract-tested by
   a golden corpus. New exclusions require a spec change, not a parser patch.
3. **Stricter than bm — explicit-only observations:** no implicit `Note`
   category for bare `#tag` lines, and relation lines with prose tails are
   prose (implicit `links_to`), never junk relation types. Accidental capture
   is worse than no capture.
4. **Beyond bm:** stable-identity rule with layered enforcement + alias-backed
   atomic renames; value references via native Obsidian embeds with defined
   missing/cycle/depth semantics; per-model observation variants
   (`[category | scope]`, mcp-hub heritage); attribution (`origin`) and scopes
   in frontmatter; inbox/review contracts as reserved-folder semantics.
5. **Taxonomy v1 is small** (9 types) and open — unknown types warn, never
   fail; task/event/meeting deliberately excluded (volatile-by-nature content
   is not long-term memory).
6. **Engine-private state lives in `.palaia/`** inside the vault root,
   gitignored and rebuildable — the vault directory is self-contained
   (movable/backupable as one folder) without the index ever becoming truth.

## Alternatives considered

- **Implicit observations (bm behavior)** — rejected: production noise,
  transcript/checkbox false positives drove years of exclusion patches.
- **Propagating value updates (engine rewrites copies)** — rejected: git
  noise, conflicts with human edits, breaks files-as-truth; read-time embed
  resolution gives the same outcome copy-free.
- **Permalink-in-filename (identity = path)** — rejected: every move/rename
  would be an identity event; Obsidian users move files constantly.
- **Rename mints redirect notes** (tombstone files) — rejected in favor of
  `aliases` frontmatter + full backlink rewrite: no litter, still resolvable.
- **Rich type system in v1** — rejected: structure should emerge (schema-as-
  notes, Phase 2+); a big upfront taxonomy would be wrong and sticky.
- **YAML-free format (all semantics in body)** — rejected: frontmatter is the
  Obsidian-native place for metadata and the properties UI edits it.

## Consequences

- SPEC-103 implements against the corpus; grammar changes REQUIRE a spec PR
  touching `docs/vault-format.md` + corpus first (format-first rule).
- SPEC-102 must implement alias-aware rename and checksum move detection as
  specified; SPEC-106 implements variant resolution and embed semantics.
- Importers must down-convert foreign constructs per §11 rather than extend
  the grammar ad hoc.
