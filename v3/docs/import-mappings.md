# Import mappings — palaia v2 and basic-memory

> Companion to [`vault-format.md`](vault-format.md) §11 (Interop notes) and
> [SPEC-111](../specs/SPEC-111-importers.md). Implemented in
> `server/src/palaia_hub/importers/`; golden fixtures and their expected
> output live in `server/tests/fixtures/import-v2/` and
> `server/tests/fixtures/import-basic-memory/`, exercised by
> `server/tests/importers/`.

Both importers are read-only clean-room re-implementations of the source
on-disk format: neither imports code from the v2 `palaia/` package (the
hard track-separation rule in `AGENTS.md` forbids that regardless of
license) nor from basic-memory (AGPL-3.0, ADR-002 — this repository does not
even vendor a copy of it; the mapping below is built against the public
concept dossier in `research/basic-memory.md` and against v3's own grammar).

Both importers:

- write only into a dedicated folder (`imported/v2/` or
  `imported/basic-memory/`; v2 `task`s go to `inbox/` instead — see below),
  so a review/rollback is "delete that folder and revert the commits", never
  a scan of the whole vault;
- mint every new permalink **deterministically from the source item's own
  stable identity** (v2 entry `id`; basic-memory's old `permalink`, or its
  file path if it never had one) — never from title or content, since those
  can be volatile or absent. Re-running an import with an unchanged source
  therefore proposes the exact same permalinks, which is what makes the
  re-run idempotent: every one of them already resolves in the vault, so
  the runner reports `already-imported` and writes nothing;
- run through `VaultEngine.write_note(..., must_create=True)`, so each new
  note is its own attributed git commit — an import of *N* mappable items is
  *N* commits, in source order: a reviewable, revertable commit series, not
  one opaque batch;
- record full source provenance under an `import` frontmatter key (an
  unknown key, format spec §2: preserved verbatim, searchable metadata) —
  never overloading the format spec's own `origin` schema, which has a
  fixed key set;
- fall back to a generic, stable, volatility-free title
  (`Imported <source> entry <hash>`) when the source title carries a
  version/date-shaped token that the writer rejects (format spec §4.1),
  preserving the original in an `- [imported-title] <text>` observation
  line — volatility rules bind titles/permalinks/link targets, never body
  content, so nothing is lost.

## palaia v2 → v3

Source: a v2 `.palaia/` store — `hot/`, `warm/`, `cold/` tier directories of
one Markdown-with-frontmatter file per entry (`palaia/entry.py`,
`palaia/store.py` in the v2 tree, read only as an on-disk format reference).
Whichever storage backend (`sqlite` or `postgres`, `palaia/backends/`) the
v2 store uses only affects its metadata index and embedding cache — entry
*content* always lives in these per-tier files, so reading the tier
directories covers both backends without touching either one's database.

| v2 field | v3 destination | Notes |
|---|---|---|
| `type: memory` | `type: note`, folder `imported/v2/notes/` | — |
| `type: process` | `type: process`, folder `imported/v2/processes/` | — |
| `type: task` | `type: capture`, folder `inbox/` | No v3 type matches a v2 task; routed through the inbox contract (format spec §7) so a curator files or discards it. Body becomes a capture's `[entity]`/`[why]`/`[raw]` shape; `status`/`priority`/`assignee` are folded into the `[raw]` text rather than invented v3 frontmatter keys. |
| other/unknown `type` | `type: note` + an `- [import-note]` body line naming the original type | Warn-first: an unexpected legacy type is imported, not rejected. |
| `tier` (`hot`/`warm`/`cold`) | `import.tier` + `import.decay_seed` (`1.0`/`0.5`/`0.1`) | A **documented seed**, not SPEC-104's live decay model (not merged yet) — a future reindex is expected to recompute real scores from access history. |
| `scope` (`team`/`private`/`public`) | v3 `scope` (`project`/`private`/`shared`) | Closest match to MASTERPLAN §5.1's three-scope model. |
| `tags` | `tags` | Copied through. |
| `title` | v3 `title` (or the sanitized fallback, see above) | Falls back to the first non-empty body line if absent. |
| `id`, `decay_score`, `access_count`, `created`, `project`, `agent` | `import.source_*` | Full provenance, never overwriting v3's own `created`/`modified` (engine-maintained). |

**Unmappable** (reported with a reason, nothing written): a file that
cannot be decoded as UTF-8; a file with no `id` field (no stable identity to
mint a permalink from); a file with an empty body (v2's own writer refuses
to create these, but a hand-edited store might contain one).

## basic-memory → v3

Source: a basic-memory vault — a flat-or-nested tree of Markdown entities,
each with `title`/`type`/`tags`/`permalink`/`schema`/`created`/`modified`
frontmatter and free-form custom keys (`research/basic-memory.md` §1).

| basic-memory field | v3 destination | Notes |
|---|---|---|
| `title` | v3 `title` (or the sanitized fallback) | — |
| `type` (default `note`) | v3 `type`, unchanged | Same taxonomy default. |
| `tags`, `schema` | copied through unchanged | Same key names in both formats. |
| `permalink` | becomes an alias; v3 mints its own (deterministic, from the old value) | Format spec §11: "permalinks are regenerated with an alias to the old value." |
| any other custom key | preserved verbatim | Same §2 "unknown keys" rule on both sides. |
| `created`, `modified` | `import.source_created` / `import.source_modified` | v3's own `created`/`modified` are engine-maintained, stamped at import time. |

Body grammar is close enough between the two formats (both are
`- [category] text #tags (context)` for observations, `- rel_type
[[Target]] (context)` for relations) that most lines need no rewriting at
all. Two specific gaps are bridged:

- basic-memory treats a **bare bullet with no `[category]`** as an implicit
  `Note`-category observation; v3's explicit-only rule (format spec §5.1)
  would otherwise silently downgrade the same line to inert prose. The
  importer rewrites it to `- [note] <text>` instead — matching format spec
  §11's "their implicit `Note`-category observations import as `[note]`
  observations."
- a basic-memory relation line carrying prose *after* the wikilink (basic-
  memory tolerates this; v3's stricter §5.2 grammar does not) is left
  untouched — it parses as plain prose with an implicit `links_to`, which is
  exactly "their relation lines with prose tails import as prose."

Left alone entirely: bullets already carrying an explicit `[category]`
(including checkbox task markers, which both formats already exclude —
format spec E1), bullets that already match v3's relation grammar, bare
`[[Target]]` wikilink bullets (already an explicit `links_to` on both
sides), and anything inside a fenced code block or a blockquote.

**Unmappable** (reported with a reason, nothing written): a non-Markdown
file (basic-memory indexes attachments as opaque entities; v3 import does
not ingest attachments in v1); a file whose frontmatter fence is present but
unparseable YAML; a file that cannot be decoded as UTF-8.

## Cold-embed as a background job (honest scope note)

SPEC-104 (index + search, including vector embedding) is a separate,
parallel, not-yet-merged SPEC. Import therefore **never blocks on
embedding**: notes land on disk (and are immediately FTS-searchable the
moment a search index exists, since files are the only truth) via the same
synchronous write-through path as any other engine write. What this SPEC
adds is a seam for the embedding work that SPEC-104 (or a later wiring
SPEC) will actually perform: every imported note's permalink is appended to
a per-vault queue file (`.palaia/import-embed-queue.jsonl`,
`importers/embed_queue.py`), and `queue_status()` reports a pending/embedded
count in the same shape as SPEC-107's `inbox_status` — so a dashboard tile
or an `embed_status`-style API call already has something correctly-shaped
to read. **No embedding is actually computed here** — there is no model
wired into this codebase yet; the queue is deliberately append-only and
never marks anything embedded until a future worker exists to do it
honestly.
