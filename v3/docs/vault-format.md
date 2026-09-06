# palaia Vault Format — Specification v1.0

> **Normative.** This document defines the on-disk format of a palaia v3 vault.
> The conformance corpus in [`vault-format-conformance/`](vault-format-conformance/)
> is the executable contract; SPEC-103's parser MUST pass it entirely. Design
> rationale lives in [ADR-003](../decisions/003-vault-format.md); the decision
> inputs are `research/memory-design-comparison.md` and the SPEC-002/003 spike
> findings.
>
> Keywords MUST / MUST NOT / SHOULD / MAY are RFC-2119. Status: draft pending
> owner sign-off (SPEC-004 acceptance).

## 0. Design invariants

1. **Files are the only truth.** Everything in this spec is plain UTF-8 Markdown
   in ordinary folders. Any state not derivable from the files is not vault state.
2. **Obsidian opens it undamaged.** Every construct renders acceptably in stock
   Obsidian; wikilinks feed its graph view; embeds render natively.
3. **Formally specified, versioned, warn-first.** The grammar below is exhaustive.
   Parsers MUST NOT reject user content: anything that fails a rule degrades to
   plain Markdown plus a machine-readable warning (§9). Only the engine's own
   *writes* are held to canonical form.
4. **Stable identity.** Names identify; attributes describe. Volatile data never
   lives in names or link targets (§4).

## 1. Vault layout

```
<vault-root>/
├── meta/
│   └── vault.md            # REQUIRED vault manifest (§1.2)
├── inbox/                  # RESERVED: uncurated captures (§7)
├── review/                 # RESERVED: curator proposals (§8)
├── <topic folders>/        # free structure — the human's taxonomy
│   └── <note>.md
└── .palaia/                # engine-private (index, state) — NOT vault content,
                            #   gitignored, rebuildable, never authoritative
```

- A **note** is one `.md` file (UTF-8, LF or CRLF accepted; engine writes LF).
  Non-Markdown files MAY live in the vault (attachments); they are indexed as
  opaque entities (path + metadata only), never parsed.
  A file that is not valid UTF-8 is still listed, read and searched — with
  U+FFFD where its bytes could not be decoded — but the engine refuses to
  edit it rather than write those replacement characters back over the
  original bytes; the doctor reports it as `not-utf8` with the conversion
  to run. A rename still rewrites such a file's backlinks, byte-preserving.
- **Folders are the human's**: any depth, any names, except the three reserved
  ones (`meta/`, `inbox/`, `review/`) which have the semantics defined here.
- Layout guidance (not conformance): prefer topic folders; keep directories
  under ~500 files — git tree-object cost per commit scales with directory
  size (SPEC-003 finding), and humans can't browse flat dumps either.
- **Filenames** SHOULD be the slugified title (`API Gateway.md` or
  `api-gateway.md` both acceptable). Identity does NOT live in the filename —
  it lives in the permalink (§3). Renaming/moving a file never changes identity.

### 1.1 Format versioning

The manifest (§1.2) carries `vault_format: 1`. Parsers MUST refuse versions
they don't know **for engine writes** and MUST fall back to read-only
best-effort **for reads**, surfacing a `format-version` warning. Evolution
policy: additive changes bump the minor concept (documented in this file's
changelog section); breaking changes bump the major and REQUIRE a migration
command. There are no silent format drifts.

### 1.2 Vault manifest — `meta/vault.md`

```markdown
---
title: Vault
permalink: meta/vault
type: meta
vault_format: 1
name: work
purpose: Team knowledge for ACME engineering — decisions, conventions, gotchas.
---

One paragraph a human (and the connect-a-client page) can read.
```

`name` and `purpose` feed the gateway's tool naming and description rules
(MASTERPLAN §5.2). The engine creates this file at vault init; a vault without
it is importable but not servable.

## 2. Frontmatter

YAML between `---` fences at file start. Parsers MUST apply these
normalizations (bm-lesson: user YAML is hostile):

- BOM stripped. A file with **no `---` fence at all** (incl. empty and
  whitespace-only files) is a perfectly ordinary plain note — NO
  `frontmatter-malformed` warning (warn-first: bare Obsidian notes are normal
  content); it gets `title-defaulted` and `permalink-missing` like any
  uncanonical note. `frontmatter-malformed` fires only when a fence is
  *present but broken*: unparseable YAML, or an opening `---` never closed.
- Scalars coerced to strings where the schema says string (dates, numbers,
  booleans arriving via YAML native types); list-valued `title` → first item,
  warning `title-coerced`.
- Unknown keys are **preserved verbatim** and indexed as searchable metadata.

### 2.1 Key schema

| Key | Req | Type | Semantics |
|---|---|---|---|
| `title` | R* | string | Human name. *Default: filename stem (warning `title-defaulted`) |
| `permalink` | R* | string | Stable identity (§3). *Assigned by the engine on first index if absent |
| `type` | O | string | Taxonomy §6; default `note`; unknown types are valid (warning `type-unknown`, warn-first philosophy) |
| `tags` | O | list \| comma-string | Normalized to a list of lowercase strings |
| `created` / `modified` | O | ISO 8601 | Engine maintains on write; external edits: `modified` from file mtime at index time |
| `scope` | O | `private` \| `project` \| `shared` | Access scope (MASTERPLAN §5.1); default: vault's configured default |
| `origin` | O | map | Attribution: `provider`, `client`, `session`, `agent`, or `human: true`. Engine-written; free-form for humans |
| `aliases` | O | list | Former titles/permalinks after renames (§4.2); resolvers honor them |
| `status` | O | string | Lifecycle for `capture`/`proposal` types (§7/§8) |
| `capture_id` | O | string | Inbox contract (§7) |
| `schema` | O | string \| map | Reserved for schema-as-notes (Phase 2+; parsers pass it through) |

### 2.2 Canonical write form

Engine writes MUST: order keys as in the table above (unknown keys after,
alphabetically), quote strings only when YAML requires it, use ISO 8601 UTC
timestamps, LF line endings, exactly one blank line after the closing `---`.
Canonical form is a writer duty, never a read requirement.

## 3. Permalinks & `memory://` addressing

### 3.1 Permalink

- Charset: `[a-z0-9]` and `-`, segments joined by `/` mirroring the folder
  path at creation time (`projects/api-gateway`). MUST be unique per vault.
- **Stability:** the permalink NEVER changes on file move or file rename.
  After a move, path and permalink diverge — that is normal and expected.
  Only an explicit identity rename (§4.2) mints a new permalink.
- Assignment: the engine slugifies the title and prefixes the folder path.
  Files arriving without a permalink (imports, hand-created notes) get one
  assigned at first index via an attributed write-back commit.
- A user-supplied permalink violating the charset is **kept verbatim**
  (identity is never silently rewritten) with warning `permalink-noncanonical`;
  the doctor offers canonicalization through the rename machinery (§4.2), so
  the old value survives as an alias.

### 3.2 `memory://` URLs

```
memory://<vault>/<permalink>          fully qualified
memory://<permalink>                  default vault of the calling token
memory://projects/api-*               glob: * within a segment, ** across
memory://<permalink>#^<block-id>      a block inside a note (§5.4)
memory://<permalink>/obs/<cat>/<h8>   synthetic observation permalink (§9.2)
memory://<permalink>/rel/<type>/<target>  synthetic relation permalink (§9.2)
```

Resolution order for a bare string: exact permalink → alias (§4.2) → exact
title (case-insensitive) → unique path suffix. Ambiguity is an error listing
the candidates, never a silent pick.

## 4. Stable identity

### 4.1 Volatility rule

Titles, permalinks and wikilink targets MUST be **volatility-free**: no version
numbers, dates, release tags, statuses, or measured values.

```
WRONG:  [[OpenClaw 2026.5.7]]     [[Server offline]]      [[Preise Stand 2026-08]]
RIGHT:  [[OpenClaw]] with          [[Server]] with         [[Preise]] with
        - [version] 2026.5.7       - [status] offline …    - [stand] 2026-08 …
```

Enforcement is layered, matching invariant 3: the **writer** (engine tools)
rejects new titles matching volatility patterns; the **doctor** flags existing
violations; the **curator** proposes fixes. The parser itself only warns
(`volatile-name`) — user files are never rejected. **Parser scope is exactly
the token patterns** (conformance-enumerated): semver-like tokens, ISO dates,
`vX.Y` forms. Conceptual volatility without such a token (`[[Server offline]]`)
is NOT a parse-time warning — judging it needs semantics and belongs to the
writer/doctor/curator layers.

### 4.2 Rename semantics

An identity rename (`rename_entity`, SPEC-102) is atomic and total:

1. New title, new permalink minted.
2. Old title and old permalink appended to `aliases`.
3. **Every** inbound wikilink in the vault rewritten to the new title.
4. One git commit for the entire operation.

Resolvers MUST honor `aliases`, so `memory://` references written before the
rename keep working. A partial rename (e.g. a human renaming in Obsidian
without backlink rewrite) is a doctor finding, not data loss: checksum-based
move detection (§10) preserves identity, and old links resolve via title
history in the index.

## 5. Body grammar

The note body is Markdown. palaia's semantic layer is carried by **exactly
three constructs**: observation lines, relation lines, and wikilinks/embeds.
Nothing else in the body has machine semantics. Grammar first, then the
exclusions that keep ordinary Markdown ordinary.

Lexical conventions for the EBNF: `WS` = spaces/tabs; `TEXT` = any characters
to end of line except where narrowed; all matching is per-line after the
line-context filter (§5.5).

### 5.1 Observations

An observation is one categorized, atomic fact about the note's entity.

```ebnf
observation   = indent? bullet WS "[" category ( WS? "|" WS? scope )? "]"
                WS obs-text ( WS context )? ( WS block-anchor )? EOL ;
bullet        = "-" | "*" ;
indent        = WS ;                     (* nesting allowed, semantics-free *)
category      = cat-char { cat-char } ;  (* 1..64 *)
cat-char      = ALPHA | DIGIT | "-" | "_" | " " ;   (* no "|", "[", "]" *)
scope         = provider [ "/" model-id ] | "default" ;
provider      = lc-word ;                (* e.g. anthropic, openai, google *)
model-id      = lc-word { lc-word | DIGIT | "-" | "." } ;
obs-text      = TEXT-NO-PAREN-TAIL ;     (* may contain #tags, [[wikilinks]] *)
context       = "(" TEXT-NO-RPAREN ")" ; (* only as the line's last non-anchor token *)
block-anchor  = "^" ANCHOR-ID ;          (* Obsidian block id, §5.4 *)
```

Rules:

- `category` MUST NOT be date- or timestamp-shaped (`[2026-08-22]`,
  `[00:01:23]` — those lines are plain Markdown; exclusion E4).
- Inline `#tags` inside `obs-text` are extracted as observation tags AND
  remain part of the text.
- Inline `[[wikilinks]]` inside `obs-text` are extracted as implicit
  `links_to` relations (§5.2) — an observation can point at entities.
- **Explicit-only:** a list item without a leading `[category]` is plain
  Markdown — even if it carries #tags. (Deliberate divergence from
  basic-memory's implicit `Note` category: accidental capture is worse than
  no capture. ADR-003 records this.)

**Per-model variants.** Consecutive observation lines with the same `category`
where some carry a `scope` form a variant group. Resolution (SPEC-106):
`provider/model` exact match > `provider` match > scopeless base. Exactly one
line of a group is served to a given caller. A group with only scoped lines
and no base is valid; callers matching nothing get nothing (warning
`variant-no-base` at parse time).

```markdown
- [how-to-apply] Prefer the compact form of this rule.
- [how-to-apply | anthropic/opus-5] Use the extended form with rationale.
- [how-to-apply | openai] Use imperative phrasing.
```

### 5.2 Relations

A relation is a typed, directed edge from this note to another entity.

```ebnf
relation      = indent? bullet WS rel-type WS wikilink ( WS context )? EOL ;
rel-type      = bare-type | quoted-type ;
bare-type     = lc-word { "_" lc-word } ;         (* relates_to, part_of *)
quoted-type   = '"' TEXT-NO-QUOTE '"' ;           (* "pairs well with" *)
wikilink      = "[[" target ( "#" anchor )? ( "|" display )? "]]" ;
target        = TEXT-NO-BRACKET-PIPE-HASH ;       (* title or permalink *)
```

Rules:

- A relation line is **exactly** the production above. A bullet line whose
  wikilink is followed by anything other than an optional `(context)` is NOT
  a relation — it is prose, and its wikilinks become implicit `links_to`
  (stricter formalization of the bm fallback; no junk relation types, ever).
- `- [[Target]]` (bullet, no type) → explicit `links_to`.
- Any `[[Target]]` elsewhere (prose, observation text, tables) → implicit
  `links_to` with the surrounding line as context.
- Relation types are **open vocabulary**. Conventions (not enforced):
  `relates_to`, `part_of`, `depends_on`, `supersedes`, `decided_in`,
  `documented_in`, `owned_by`.
- **Forward references** are first-class: `target` MAY name an entity that
  does not exist yet. The parse result carries the target name unresolved;
  the index resolves it when (if) the entity appears — no reindex, no error.

### 5.3 Value references (embeds)

Shared values are referenced, never copied (MASTERPLAN §5.1).

```ebnf
embed         = "!" wikilink ;            (* ![[Note]], ![[Note#^rate]], ![[Note#Heading]] *)
```

- Anchored embeds (`#^block-id`, `#Heading`) reference a block or section;
  bare embeds reference the whole note.
- **Resolution is read-time** (SPEC-106): recall/read output replaces the
  embed with the current source content. On disk the reference stays a
  reference — no propagation machinery, no stale copies. Obsidian renders the
  same embeds natively, so humans see the live value too.
- Failure semantics (conformance-tested): missing target → the literal marker
  `⟦missing: <target>⟧` in resolved output plus warning `embed-missing`;
  cycle → resolution stops at the repeated node with `⟦cycle: <chain>⟧` plus
  warning `embed-cycle`. Never silently dropped, never an exception.
  `<chain>` is the note **titles** along the resolution path, arrow-separated,
  with the repeated node written out at the end: `⟦cycle: Note A → Note B →
  Note A⟧`; a self-embed renders `⟦cycle: Note A → Note A⟧`. `<target>` in
  markers is the target as written in the embed.
- Depth limit: **the entry note's own embed is hop 1**; hops 1–8 resolve,
  hop 9 renders `⟦depth: <target>⟧` (so a 10-note linear chain is the minimal
  structure that exercises the cap).

### 5.4 Block anchors

```ebnf
block-anchor  = "^" ANCHOR-ID ;
ANCHOR-ID     = ( ALPHA | DIGIT | "-" ) {1,32} ;
```

A block anchor at the end of any line (Obsidian convention) makes that line
addressable: `memory://<permalink>#^<id>` and `![[Note#^<id>]]`. Anchors on
observation lines make **fields**: `- [rate-limit] 100 req/min ^rate-limit`
is the single source other notes embed. **Every** anchor in a note — on
observation lines and ordinary lines alike — surfaces in the parse result's
top-level `anchors` array (§9); duplicates within one note warn
`anchor-duplicate` (first occurrence wins for resolution).

### 5.5 Exclusions — what is NEVER an observation/relation

Learned from basic-memory's patch history; here they are grammar, not patches.
A line matching any exclusion is plain Markdown (E1–E7 conformance-tested):

- **E1 Task markers:** `- [ ]`, `- [x]`, `- [X]`, `- [/]`, `- [>]`, `- [-]`
  (any checkbox-like single-char category from the set ` xX/>-~?!iI`).
- **E2 Code:** anything inside fenced (``` / ~~~) or 4-space-indented code
  blocks, inline code spans excluded from link/tag extraction too.
- **E3 Callouts & quotes:** lines inside blockquotes (`>` prefix), including
  Obsidian callouts `> [!info]`.
- **E4 Numeric/date/time-shaped categories:** a category matching a date
  shape (`YYYY-MM-DD`), a time shape (`HH:MM`, `HH:MM:SS`), or consisting
  **only of digits** (`[2026]`, `[42]`) — transcripts and logs stay prose;
  a purely numeric token has no value as a category.
- **E5 Markdown links:** `[text](url)` is never a category; `[text][ref]`
  reference-style links likewise.
- **E6 Footnotes:** `[^1]` definitions and references.
- **E7 Tables and headings:** `|`-rows and `#`-prefixed lines carry no
  observation/relation semantics.

Exclusions suppress observation/relation-**line** semantics only. **Wikilink
extraction (implicit `links_to`) applies on all excluded lines except inside
code (E2)** — a checkbox task or a quoted line referencing `[[An Entity]]`
still feeds the graph, exactly as Obsidian's own graph view treats them.

## 6. Entry taxonomy v1

`type` values with defined semantics (unknown types remain valid, warn-first):

| type | Semantics | Special handling |
|---|---|---|
| `note` | Default knowledge entity | — |
| `decision` | A decision + its why | Recall boosts for "why do we…" queries |
| `rule` | Standing instruction for agents | Primary `recall` scope; per-model variants expected here |
| `process` | How-to / runbook | Step lists stay plain Markdown (E1!) |
| `person` | A person | Scope-sensitive by default |
| `project` | A project/product entity | Anchor for `part_of` graphs |
| `capture` | Raw inbox entry | Only valid in `inbox/` (§7) |
| `proposal` | Curator maintenance proposal | Only valid in `review/` (§8) |
| `meta` | Vault self-description | `meta/` only; excluded from normal recall |

Types deliberately absent from v1 (revisit with schema-as-notes, Phase 2+):
task, event, meeting — volatile-by-nature content belongs in stash or in
`process`/`decision` notes, not as first-class memory types.

## 7. Inbox contract (`inbox/`)

A capture is a note a busy agent can drop without knowing the vault taxonomy
(SPEC-107; mcp-hub heritage). Canonical form:

```markdown
---
title: Rate limit decision from PR review
permalink: inbox/rate-limit-decision-from-pr-review
type: capture
tags: [inbox]
status: uncurated
capture_id: cap-3f9a1c02d4
origin: { provider: anthropic, client: claude-code, session: s-9021 }
created: 2026-08-22T14:30:00Z
---

One sentence: what this capture is about.

- [entity] API Gateway
- [why] The limit was chosen deliberately; future work will trip over it otherwise.
- [raw] We capped ingest at 100 req/min because the embed queue saturates above that; raising it requires batching first (see PR #88 discussion).
- [source] PR #88 review, cwendler, 2026-08-22
```

Rules:

- `[entity]` and `[why]` are MANDATORY — a capture missing either is routed to
  `review/` by the curator, never guessed at.
- `capture_id` = `"cap-" + sha256(permalink)[:10]`, engine-derived if absent.
- `status: uncurated` keeps the capture fully searchable immediately.
- Lifecycle: `uncurated` → (curator) → deleted-after-verification, or
  `curation-failed` after 3 attempts (failures appended as
  `- [curation-failed] <ISO ts>: reason` — additive, never destructive).
- Nothing may *create* non-capture notes in `inbox/`; the curator may not
  edit `inbox/` content (guard-enforced, Phase 2).

## 8. Review contract (`review/`)

Curator MAINTENANCE proposals (Phase 2 detail lives with the curator SPEC;
the format is fixed here so Phase-1 tooling reserves it correctly):

- `type: proposal`, `status: proposed | approved | rejected | applied |
  apply-failed | manual` — `approved` is the queue; every apply run ends in a
  terminal status.
- The proposal body is human-readable; an optional fenced ```json block named
  `plan` carries typed operations for the deterministic apply pass.
  Pre-images of touched notes are appended to the proposal before any apply.
- Humans approve by flipping `status` — in Obsidian, in the dashboard, or in
  the review-queue MCP App; all three edit the same frontmatter field.

## 9. Canonical parse result

The conformance corpus asserts against this JSON shape (SPEC-103's output;
field order irrelevant, absent optionals omitted):

```json
{
  "format_version": 1,
  "path": "projects/api-gateway.md",
  "title": "API Gateway",
  "permalink": "projects/api-gateway",
  "type": "note",
  "tags": ["infra"],
  "frontmatter": { "…normalized, incl. unknown keys…": true },
  "observations": [
    { "category": "rate-limit", "scope": null, "text": "100 req/min #infra",
      "tags": ["infra"], "context": "set in PR #88", "block_id": "rate-limit",
      "line": 9 }
  ],
  "relations": [
    { "type": "part_of", "target": "ACME Platform", "context": null,
      "implicit": false, "line": 12 }
  ],
  "embeds": [
    { "target": "Pricing", "anchor": "^base-rate", "line": 15 }
  ],
  "anchors": [
    { "id": "rate-limit", "line": 9 }
  ],
  "warnings": [ { "code": "volatile-name", "line": 3, "detail": "…" } ]
}
```

### 9.1 Warning codes (closed list for v1)

`frontmatter-malformed`, `title-defaulted`, `title-coerced`, `type-unknown`,
`permalink-missing`, `permalink-noncanonical`, `volatile-name`,
`variant-no-base`, `embed-missing`*, `embed-cycle`*, `format-version`,
`anchor-duplicate`.
(*emitted at resolution time, not parse time — listed here because the corpus
covers them.)

### 9.2 Synthetic permalinks

Observations and relations are addressable in search results:
`<permalink>/obs/<category-slug>/<h8>` (h8 = sha256 of the observation text,
first 8 hex) and `<permalink>/rel/<type-slug>/<target-permalink>`. These are
derived, never stored in files.

## 10. External edits, moves, integrity

- The watcher treats a same-batch `deleted(old)+added(new)` pair with equal
  content checksum as a **move**: permalink, history and relations are
  preserved (SPEC-003 finding: watchfiles has no rename event — this rule is
  what stops Obsidian renames from severing identity).
- Every engine write is atomic (tmp + fsync + rename) and becomes one
  attributed git commit; external edits are committed on next engine activity
  with `origin: { human: true }`.
- The index is disposable: `reindex` MUST reproduce identical query results
  from files alone (SPEC-104 acceptance); `doctor verify` reports file↔index
  drift, stale git locks, volatility violations, and partial renames.

## 11. Interop notes

- **basic-memory import** (SPEC-111): frontmatter maps 1:1 where names match;
  their implicit `Note`-category observations import as `[note]` observations
  (explicitly marked `origin: {import: basic-memory}`); their relation lines
  with prose tails import as prose (our stricter §5.2 applies); permalinks are
  regenerated with an alias to the old value.
- **palaia v2 import**: entries become typed notes (`memory`→`note`,
  `process`→`process`, `task`→dropped-to-inbox for curation); tiers seed decay
  scores; scopes carry over.
- **Obsidian**: everything here renders; `.obsidian/` is ignored by the
  engine; the git plugin sees the same attributed history the engine writes.

## 12. Changelog

- **1.0-draft (2026-08-22)** — initial specification. Owner sign-off pending;
  becomes 1.0 when ADR-003 is Accepted.
- **1.0-draft.2 (2026-08-22)** — nine corpus-authoring ambiguities resolved
  (AMBIGUITIES.md): parser scope of `volatile-name`; cycle-chain and
  depth-cap worked examples; missing-vs-malformed frontmatter; new
  `permalink-noncanonical` warning; E4 covers purely numeric categories;
  top-level `anchors` array; wikilink extraction on excluded lines (except
  code).
