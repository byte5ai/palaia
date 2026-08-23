"""The disposable projection's SQL schema.

Nothing in here is a source of truth: every table is derivable from the
notes on disk (format spec §10, "the index is disposable"), which is why the
migration story is *drop and rebuild* rather than ALTER TABLE — a schema
version bump wipes the file and reindexes from files.

Two deliberate deviations from the obvious design:

* ``notes.path`` is the UNIQUE key, ``notes.permalink`` only an index.
  Duplicate permalinks are a doctor *finding* (``permalink-duplicate``), not
  something the index may refuse to represent — warn-first applies here too.
* full text lives in ``search_rows`` (one row per addressable thing: a note,
  an observation, a relation) with an external-content FTS5 table kept in
  sync by triggers. That is what gives sub-note addressability (§9.2): an
  observation hit carries its own synthetic permalink, and deleting a note's
  rows is a plain ``DELETE ... WHERE note_id = ?`` instead of the
  re-supply-the-old-values dance contentless FTS5 deletes require.
"""

from __future__ import annotations

#: Bumping this drops the database file and triggers a full reindex.
SCHEMA_VERSION = 1

#: Metadata keys stored in the ``meta`` table.
META_SCHEMA_VERSION = "schema_version"
META_EMBED_MODEL = "embed_model"
META_EMBED_DIM = "embed_dim"
META_VAULT = "vault"

#: Row kinds in ``search_rows`` — the three addressable granularities.
KIND_NOTE = "note"
KIND_OBSERVATION = "observation"
KIND_RELATION = "relation"

#: FTS5 tokenizer: unicode61 with diacritic folding so "Farah Al-Sayed"
#: matches "Farah Al Sayed", and with ``-``/``_``/``/`` kept as separators
#: (the default) so permalink-ish queries split into their words.
_TOKENIZER = "unicode61 remove_diacritics 2"

SCHEMA_SQL = f"""
CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE notes (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    permalink   TEXT NOT NULL,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL,
    folder      TEXT NOT NULL,
    tags        TEXT NOT NULL,          -- JSON array, lowercased
    aliases     TEXT NOT NULL,          -- JSON array
    created     TEXT,
    modified    TEXT,
    checksum    TEXT NOT NULL,
    body        TEXT NOT NULL,
    frontmatter TEXT NOT NULL           -- JSON object, verbatim (§2.1)
);
CREATE INDEX notes_permalink ON notes(permalink);
CREATE INDEX notes_type ON notes(type);
CREATE INDEX notes_folder ON notes(folder);
CREATE INDEX notes_modified ON notes(modified);

-- Every string a note answers to (permalink, title, aliases, and their
-- slugs). Both directions of reference resolution join through this table.
CREATE TABLE note_keys (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    key     TEXT NOT NULL
);
CREATE INDEX note_keys_key ON note_keys(key);
CREATE INDEX note_keys_note ON note_keys(note_id);

CREATE TABLE note_tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL
);
CREATE INDEX note_tags_tag ON note_tags(tag);
CREATE INDEX note_tags_note ON note_tags(note_id);

-- Flattened frontmatter scalars, including unknown keys: format spec §2.1
-- says unknown keys are "preserved verbatim and indexed as searchable
-- metadata", so custom-key filters are a first-class deliverable.
CREATE TABLE note_meta (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL
);
CREATE INDEX note_meta_key_value ON note_meta(key, value);
CREATE INDEX note_meta_note ON note_meta(note_id);

CREATE TABLE observations (
    id        INTEGER PRIMARY KEY,
    note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    permalink TEXT NOT NULL,            -- synthetic (§9.2)
    category  TEXT NOT NULL,
    scope     TEXT,
    text      TEXT NOT NULL,
    tags      TEXT NOT NULL,            -- JSON array
    context   TEXT,
    block_id  TEXT,
    line      INTEGER NOT NULL
);
CREATE INDEX observations_note ON observations(note_id);
CREATE INDEX observations_category ON observations(category);

CREATE TABLE relations (
    id               INTEGER PRIMARY KEY,
    note_id          INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    permalink        TEXT NOT NULL,     -- synthetic (§9.2)
    type             TEXT NOT NULL,
    target_raw       TEXT NOT NULL,
    target_key       TEXT NOT NULL,     -- lowercased target_raw
    target_slug      TEXT NOT NULL,     -- slugified target_raw
    target_permalink TEXT,              -- NULL = unresolved forward reference
    implicit         INTEGER NOT NULL,
    context          TEXT,
    line             INTEGER NOT NULL
);
CREATE INDEX relations_note ON relations(note_id);
CREATE INDEX relations_target_permalink ON relations(target_permalink);
CREATE INDEX relations_target_key ON relations(target_key);
CREATE INDEX relations_target_slug ON relations(target_slug);

CREATE TABLE search_rows (
    id      INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,
    ref     TEXT NOT NULL,              -- addressable permalink of this row
    title   TEXT NOT NULL,
    text    TEXT NOT NULL
);
CREATE INDEX search_rows_note ON search_rows(note_id);

CREATE VIRTUAL TABLE fts USING fts5(
    title,
    text,
    content='search_rows',
    content_rowid='id',
    tokenize='{_TOKENIZER}'
);

CREATE TRIGGER search_rows_ai AFTER INSERT ON search_rows BEGIN
    INSERT INTO fts(rowid, title, text) VALUES (new.id, new.title, new.text);
END;
CREATE TRIGGER search_rows_ad AFTER DELETE ON search_rows BEGIN
    INSERT INTO fts(fts, rowid, title, text) VALUES ('delete', old.id, old.title, old.text);
END;

-- Embedding units. `fingerprint` is what makes an incremental update cheap:
-- a chunk whose text is unchanged keeps its vector and its `ready` state, so
-- editing a note's last paragraph re-embeds one chunk, not the whole note.
CREATE TABLE chunks (
    id          INTEGER PRIMARY KEY,
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    ref         TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    text        TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'pending',   -- pending | ready | failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (note_id, seq)
);
CREATE INDEX chunks_state ON chunks(state);
CREATE INDEX chunks_fingerprint ON chunks(fingerprint);
"""

#: sqlite-vec's KNN table, created lazily once the embedding dimension is
#: known (it is part of the table declaration).
VEC_TABLE_SQL = "CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}])"

__all__ = [
    "KIND_NOTE",
    "KIND_OBSERVATION",
    "KIND_RELATION",
    "META_EMBED_DIM",
    "META_EMBED_MODEL",
    "META_SCHEMA_VERSION",
    "META_VAULT",
    "SCHEMA_SQL",
    "SCHEMA_VERSION",
    "VEC_TABLE_SQL",
]
