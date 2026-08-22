---
id: SPEC-004
title: Vault format specification v1 + ADR
phase: 0
depends_on: [SPEC-002, SPEC-003]
model: fable-5
effort: high
status: ready
---

# SPEC-004: Vault format specification v1 + ADR

## Goal
The single most consequential design artifact of v3: a **formally specified,
versioned** vault format. basic-memory's grammar grew by patch-on-patch
heuristics (research/basic-memory.md §6.6); palaia writes the grammar down
first and tests against it forever. Normative inputs: the decision matrix in
research/memory-design-comparison.md (dimensions 1-8, 10-12) plus the spike
findings.

## Deliverables
1. `v3/docs/vault-format.md` — normative spec v1:
   - file/folder layout, naming, reserved folders (`inbox/`, `review/`, `meta/`);
     layout guidance informed by SPEC-003: git tree-object cost scales with
     *directory* size, so the spec favors topic folders (natural sharding) and
     sets a soft per-directory size guideline instead of flat dumps
   - frontmatter schema (required/optional keys, types, custom-key policy,
     stable permalink rules incl. move behavior)
   - observation grammar (categories, tags, context, per-model variants
     `[category | model-scope]`) as a **formal grammar (EBNF)** plus the
     exclusion cases learned from basic-memory (checkboxes, callouts,
     timestamps, links)
   - relation grammar (typed wikilinks, implicit `links_to`, forward
     references, quoted multi-word types)
   - `memory://` addressing incl. sub-note (observation/relation) permalinks
   - **stable-identity rules**: entity names / link targets must be volatility-free
     (no versions, dates, statuses); where such data lives instead; rename
     semantics (all backlinks rewritten atomically)
   - **value references**: Obsidian-compatible block/field embeds
     (`![[Note#^block]]`) as the copy-free way to share volatile values across
     notes; resolution semantics (read/recall time), cycle handling, missing-target
     behavior
   - entry taxonomy v1 (note types) — the narrowed open decision #5
   - format version marker + evolution/migration policy
2. `v3/decisions/003-vault-format.md` — ADR: what was adopted from
   basic-memory/palaia v2/mcp-hub, what deliberately differs, why
3. `v3/docs/vault-format-conformance/` — a **golden corpus**: ≥ 40 minimal
   markdown files, each exercising one grammar rule (valid + invalid + edge),
   with expected parse results as JSON siblings. This corpus is the contract
   SPEC-103 implements against.

## Acceptance criteria
- [ ] every grammar rule has ≥ 1 golden-corpus case (valid AND invalid), incl.
      volatile-name violations and value-reference resolution/cycle/missing cases
- [ ] Obsidian opens a sample vault without any rendering damage
- [ ] spike findings (SPEC-002/003) explicitly addressed where relevant
- [ ] ADR-003 lists rejected alternatives with reasons
- [ ] owner sign-off recorded in the ADR (status: Accepted)

## Non-goals
No parser implementation (SPEC-103). No schema-inference design (Phase 2+).

## Model note
**Fable 5 / effort high** — grammar mistakes propagate into every note ever
written; this is the wrong place to save tokens.
