"""Turning notes into index rows — and keeping references resolved.

This module is the only writer of the index tables. Three behaviors carry
most of the SPEC's weight:

**Batched builds.** :class:`IndexWriter` implements the vault doctor's
``ReindexSink`` protocol, and a whole rebuild runs inside **one** transaction
(``begin`` → ``emit``\\ × n → ``finish``). The spike measured an easy 5-10×
from that alone; committing per note also makes a crashed rebuild leave a
half-index behind, which a single transaction cannot.

**Forward references resolve in both directions.** ``- depends_on [[Q3
Roadmap]]`` is legal when no such note exists (format spec §5.2): the
relation is stored with ``target_permalink = NULL``. When a note that answers
to "Q3 Roadmap" later appears, :meth:`IndexWriter.upsert_note` back-resolves
every waiting relation — no full reindex, per the SPEC's acceptance
criterion. Deleting the target puts them back to NULL.

**Reindex preserves embedding work.** A rebuild does not blindly delete and
reinsert: notes are matched by path and chunks by ``(seq, fingerprint)``, so a
reindex of an unchanged vault leaves every vector in place. Editing one
paragraph re-embeds one chunk.

**A rebuild owns the connection's transaction.** Between ``begin`` and
``finish`` every commit on the database joins the rebuild (see
:meth:`~.db.IndexDatabase.commit`), and :class:`~.service.VaultIndex` holds
back incremental change events until the rebuild is over, then replays them
(issue #332). ``finish`` therefore never deletes a note that was written
during the rebuild — that note was not indexed yet — and a failure inside the
rebuild rolls the whole thing back (:meth:`IndexWriter.abort`), leaving the
previous index intact.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator, Sequence
from typing import Any

from palaia_hub.vault import IndexEntry, Note
from palaia_hub.vault import permalink as pl
from palaia_hub.vault.parse import ParsedNote, parse_note

from .db import IndexDatabase
from .embeddings import Chunk, EmbeddingConfig, chunk_text, embeddable_text
from .models import observation_permalink, relation_permalink
from .schema import KIND_NOTE, KIND_OBSERVATION, KIND_RELATION

logger = logging.getLogger("palaia_hub.index.writer")

#: Frontmatter keys with their own columns/tables — not duplicated into
#: ``note_meta``, which exists for everything else (§2.1's unknown keys).
_META_SKIP = frozenset({"title", "permalink", "type", "tags", "aliases"})


def _folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _permalink_for(note: Note, parsed: ParsedNote) -> str:
    """The identity this note is indexed under.

    A note may legitimately have no permalink yet (the engine mints one on
    first index via a write-back commit, §3.1) — until it does, the path
    without its suffix stands in, which is exactly what the gateway adapter
    already reports to callers.
    """
    return parsed.permalink or note.permalink or note.path.removesuffix(".md")


def _resolution_keys(permalink: str, title: str, aliases: Sequence[str]) -> list[str]:
    """Every lowercase string this note answers to (§3.2 resolution order)."""
    keys = {permalink.lower(), title.strip().lower(), pl.slugify(title)}
    for alias in aliases:
        alias = str(alias).strip()
        if alias:
            keys.add(alias.lower())
            keys.add(pl.slugify(alias))
    # A permalink's last segment ("projects/api-gateway" -> "api-gateway") is
    # how a wikilink usually names it.
    keys.add(permalink.rsplit("/", 1)[-1].lower())
    return sorted(key for key in keys if key)


def _flatten_meta(frontmatter: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten frontmatter into ``(key, value)`` filter rows."""
    rows: list[tuple[str, str]] = []
    for key, value in frontmatter.items():
        name = str(key)
        if name in _META_SKIP:
            continue
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, (dict, list)):
                    rows.append((f"{name}.{sub_key}", str(sub_value)))
            continue
        if isinstance(value, (list, tuple)):
            rows.extend((name, str(item)) for item in value if not isinstance(item, (dict, list)))
            continue
        rows.append((name, str(value)))
    return rows


class IndexWriter:
    """Writes one vault's index. Implements the doctor's ``ReindexSink``."""

    def __init__(self, db: IndexDatabase, embedding: EmbeddingConfig | None = None) -> None:
        self._db = db
        self._embedding = embedding or EmbeddingConfig()
        self._rebuild_seen: set[str] | None = None

    # ------------------------------------------------------- ReindexSink API

    def begin(self, vault: str) -> None:
        """Start a full rebuild: one transaction for the whole vault."""
        with self._db.lock:
            self._rebuild_seen = set()
            self._db.begin_rebuild()

    def emit(self, note: Note) -> None:
        """Index one note as part of the in-flight rebuild."""
        if self._rebuild_seen is None:  # pragma: no cover - misuse
            raise RuntimeError("emit() called outside a begin()/finish() rebuild")
        with self._db.lock:
            self._rebuild_seen.add(note.path)
            self._index_note(note)

    def finish(self) -> None:
        """Drop notes that vanished, then commit the rebuild atomically."""
        with self._db.lock:
            seen = self._rebuild_seen or set()
            stale = [
                str(row["path"])
                for row in self._db.conn.execute("SELECT path FROM notes").fetchall()
                if str(row["path"]) not in seen
            ]
            for path in stale:
                self._delete_note(path)
            orphans = self.sweep_orphan_vectors()
            self._db.end_rebuild(commit=True)
            self._rebuild_seen = None
            if stale:
                logger.debug("rebuild dropped %d stale note(s)", len(stale))
            if orphans:
                logger.debug("rebuild dropped %d orphan vector(s)", orphans)

    def abort(self) -> None:
        """Roll back an in-flight rebuild (a half-index is never committed)."""
        with self._db.lock:
            if self._rebuild_seen is not None:
                self._db.end_rebuild(commit=False)
                self._rebuild_seen = None

    # -------------------------------------------------------- incremental API

    def upsert_note(self, note: Note) -> None:
        """Index (or re-index) one note and commit."""
        with self._db.lock:
            self._index_note(note)
            self._db.commit()

    def delete_note(self, path: str) -> bool:
        """Remove one note from the index; returns whether it was present."""
        with self._db.lock:
            removed = self._delete_note(path)
            self._db.commit()
        return removed

    def move_note(self, previous_path: str, note: Note) -> None:
        """Handle a move: drop the old path's rows, index the new ones."""
        with self._db.lock:
            if previous_path != note.path:
                self._delete_note(previous_path)
            self._index_note(note)
            self._db.commit()

    def sweep_orphan_vectors(self) -> int:
        """Delete vectors whose chunk no longer exists; return how many.

        A chunk deleted while its text was out being embedded used to get its
        vector inserted anyway (issue #336) — the worker now checks before it
        inserts, and this sweep (run by every rebuild) cleans up anything that
        slipped through, so orphans cannot accumulate and crowd KNN results.
        The caller holds the lock; the caller commits.
        """
        if not self._db.has_vec_table():
            return 0
        try:
            cursor = self._db.conn.execute(
                "DELETE FROM vec_chunks WHERE rowid NOT IN (SELECT id FROM chunks)"
            )
        except sqlite3.Error:  # pragma: no cover - vec table vanished
            logger.debug("could not sweep orphan vectors", exc_info=True)
            return 0
        return int(cursor.rowcount or 0)

    # ------------------------------------------------------------- IndexView

    def index_entries(self) -> Iterator[IndexEntry]:
        """Yield one :class:`~palaia_hub.vault.IndexEntry` per indexed note.

        This is the doctor's file↔index drift check (SPEC-102 wrote its
        ``_check_index`` against this protocol before an index existed).
        """
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT permalink, path, checksum FROM notes ORDER BY path"
            ).fetchall()
        for row in rows:
            yield IndexEntry(
                permalink=str(row["permalink"]),
                path=str(row["path"]),
                checksum=str(row["checksum"]),
            )

    # ---------------------------------------------------------------- internals

    def _index_note(self, note: Note) -> None:
        conn = self._db.conn
        row = conn.execute(
            "SELECT id, permalink, checksum FROM notes WHERE path = ?", (note.path,)
        ).fetchone()
        if row is not None and str(row["checksum"]) == note.checksum:
            # Byte-identical content produces byte-identical rows, so a
            # reindex of an unchanged vault (and any event that re-emits a note
            # that did not really change) costs one SELECT per note — no parse,
            # no chunking, no writes. This is what makes "reindex on anything
            # ambiguous" an affordable strategy in the service layer.
            return
        parsed = parse_note(note.text, note.path)
        permalink = _permalink_for(note, parsed)
        aliases = list(note.aliases) or [
            str(alias) for alias in parsed.frontmatter.get("aliases", []) or []
        ]
        frontmatter = dict(parsed.frontmatter)
        values = (
            permalink,
            parsed.title,
            parsed.type,
            _folder_of(note.path),
            json.dumps(list(parsed.tags)),
            json.dumps(aliases),
            str(frontmatter.get("created") or "") or None,
            str(frontmatter.get("modified") or "") or None,
            note.checksum,
            parsed.body,
            json.dumps(frontmatter, sort_keys=True, default=str),
        )
        if row is None:
            cursor = conn.execute(
                "INSERT INTO notes(path, permalink, title, type, folder, tags, aliases, "
                "created, modified, checksum, body, frontmatter) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (note.path, *values),
            )
            note_id = int(cursor.lastrowid or 0)
        else:
            note_id = int(row["id"])
            previous_permalink = str(row["permalink"])
            conn.execute(
                "UPDATE notes SET permalink=?, title=?, type=?, folder=?, tags=?, aliases=?, "
                "created=?, modified=?, checksum=?, body=?, frontmatter=? WHERE id=?",
                (*values, note_id),
            )
            if previous_permalink != permalink:
                # The identity moved: anything pointing at the old permalink
                # is no longer resolved by it (the back-resolution below
                # re-links whatever the new identity answers to).
                self._unresolve_target(previous_permalink)
            for table in ("note_keys", "note_tags", "note_meta", "observations", "relations"):
                conn.execute(f"DELETE FROM {table} WHERE note_id = ?", (note_id,))
            conn.execute("DELETE FROM search_rows WHERE note_id = ?", (note_id,))

        keys = _resolution_keys(permalink, parsed.title, aliases)
        conn.executemany(
            "INSERT INTO note_keys(note_id, key) VALUES (?, ?)",
            [(note_id, key) for key in keys],
        )
        conn.executemany(
            "INSERT INTO note_tags(note_id, tag) VALUES (?, ?)",
            [(note_id, tag.lower()) for tag in parsed.tags],
        )
        conn.executemany(
            "INSERT INTO note_meta(note_id, key, value) VALUES (?, ?, ?)",
            [(note_id, key, value) for key, value in _flatten_meta(frontmatter)],
        )

        self._insert_note_row(note_id, permalink, parsed, aliases)
        self._insert_observations(note_id, permalink, parsed)
        self._insert_relations(note_id, permalink, parsed)
        self._sync_chunks(note_id, permalink, parsed)
        # Back-resolution: this note may be the target other notes were
        # waiting for (acceptance criterion: "forward reference resolves when
        # target note appears (no full reindex)").
        self._resolve_pending(permalink, keys)

    def _insert_note_row(
        self, note_id: int, permalink: str, parsed: ParsedNote, aliases: Sequence[str]
    ) -> None:
        # Aliases and tags join the note's searchable text so a query naming
        # an old title or a tag word still finds the note.
        extra = " ".join([*aliases, *(f"#{tag}" for tag in parsed.tags)])
        text = f"{parsed.body}\n{extra}".strip() if extra else parsed.body
        self._db.conn.execute(
            "INSERT INTO search_rows(note_id, kind, ref, title, text) VALUES (?, ?, ?, ?, ?)",
            (note_id, KIND_NOTE, permalink, parsed.title, text),
        )

    def _insert_observations(self, note_id: int, permalink: str, parsed: ParsedNote) -> None:
        conn = self._db.conn
        for obs in parsed.observations:
            synthetic = observation_permalink(permalink, obs.category, obs.text)
            conn.execute(
                "INSERT INTO observations(note_id, permalink, category, scope, text, tags, "
                "context, block_id, line) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    synthetic,
                    obs.category,
                    obs.scope,
                    obs.text,
                    json.dumps(list(obs.tags)),
                    obs.context,
                    obs.block_id,
                    obs.line,
                ),
            )
            parts = [f"[{obs.category}]", obs.text]
            if obs.context:
                parts.append(f"({obs.context})")
            parts.extend(f"#{tag}" for tag in obs.tags)
            conn.execute(
                "INSERT INTO search_rows(note_id, kind, ref, title, text) VALUES (?, ?, ?, ?, ?)",
                (note_id, KIND_OBSERVATION, synthetic, parsed.title, " ".join(parts)),
            )

    def _insert_relations(self, note_id: int, permalink: str, parsed: ParsedNote) -> None:
        conn = self._db.conn
        for rel in parsed.relations:
            target_key = rel.target.strip().lower()
            target_slug = pl.slugify(rel.target)
            resolved = self._resolve_target(target_key, target_slug)
            synthetic = relation_permalink(permalink, rel.type, resolved, rel.target)
            conn.execute(
                "INSERT INTO relations(note_id, permalink, type, target_raw, target_key, "
                "target_slug, target_permalink, implicit, context, line) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note_id,
                    synthetic,
                    rel.type,
                    rel.target,
                    target_key,
                    target_slug,
                    resolved,
                    int(rel.implicit),
                    rel.context,
                    rel.line,
                ),
            )
            text = f"{rel.type} {rel.target}"
            if rel.context:
                text = f"{text} ({rel.context})"
            conn.execute(
                "INSERT INTO search_rows(note_id, kind, ref, title, text) VALUES (?, ?, ?, ?, ?)",
                (note_id, KIND_RELATION, synthetic, parsed.title, text),
            )

    # ------------------------------------------------------------- resolution

    def _resolve_target(self, target_key: str, target_slug: str) -> str | None:
        """Resolve one relation target to a permalink, deterministically.

        Ambiguity is not an error here (that is the engine's resolver's job
        for user-facing lookups); the index picks the lowest permalink so a
        rebuild reproduces byte-identical results.
        """
        conn = self._db.conn
        for key in (target_key, target_slug):
            if not key:
                continue
            row = conn.execute(
                "SELECT n.permalink FROM note_keys k JOIN notes n ON n.id = k.note_id "
                "WHERE k.key = ? ORDER BY n.permalink, n.path LIMIT 1",
                (key,),
            ).fetchone()
            if row is not None:
                return str(row["permalink"])
        return None

    def _resolve_pending(self, permalink: str, keys: Sequence[str]) -> None:
        """Point every waiting forward reference at this note's permalink."""
        if not keys:
            return
        conn = self._db.conn
        placeholders = ",".join("?" for _ in keys)
        rows = conn.execute(
            "SELECT r.id, r.note_id, r.permalink, r.type, r.target_raw, n.permalink AS source "
            "FROM relations r JOIN notes n ON n.id = r.note_id "
            "WHERE r.target_permalink IS NULL "
            f"AND (r.target_key IN ({placeholders}) OR r.target_slug IN ({placeholders}))",
            [*keys, *keys],
        ).fetchall()
        for row in rows:
            new_ref = relation_permalink(
                str(row["source"]), str(row["type"]), permalink, str(row["target_raw"])
            )
            conn.execute(
                "UPDATE relations SET target_permalink = ?, permalink = ? WHERE id = ?",
                (permalink, new_ref, int(row["id"])),
            )
            self._retarget_search_row(int(row["note_id"]), str(row["permalink"]), new_ref)
        if rows:
            logger.debug("resolved %d forward reference(s) to %s", len(rows), permalink)

    def _unresolve_target(self, permalink: str) -> None:
        """A target disappeared: its inbound relations become forward refs again."""
        conn = self._db.conn
        rows = conn.execute(
            "SELECT r.id, r.note_id, r.permalink, r.type, r.target_raw, n.permalink AS source "
            "FROM relations r JOIN notes n ON n.id = r.note_id "
            "WHERE r.target_permalink = ?",
            (permalink,),
        ).fetchall()
        for row in rows:
            new_ref = relation_permalink(
                str(row["source"]), str(row["type"]), None, str(row["target_raw"])
            )
            conn.execute(
                "UPDATE relations SET target_permalink = NULL, permalink = ? WHERE id = ?",
                (new_ref, int(row["id"])),
            )
            self._retarget_search_row(int(row["note_id"]), str(row["permalink"]), new_ref)

    def _retarget_search_row(self, note_id: int, old_ref: str, new_ref: str) -> None:
        if old_ref == new_ref:
            return
        self._db.conn.execute(
            "UPDATE search_rows SET ref = ? WHERE note_id = ? AND kind = ? AND ref = ?",
            (new_ref, note_id, KIND_RELATION, old_ref),
        )

    # ----------------------------------------------------------------- chunks

    def _sync_chunks(self, note_id: int, permalink: str, parsed: ParsedNote) -> None:
        """Reconcile this note's embedding units, reusing unchanged vectors."""
        conn = self._db.conn
        text = embeddable_text(parsed.title, parsed.body, [obs.text for obs in parsed.observations])
        chunks = chunk_text(
            text,
            max_chars=self._embedding.max_chars,
            overlap_chars=self._embedding.overlap_chars,
        )
        existing = {
            int(row["seq"]): row
            for row in conn.execute(
                "SELECT id, seq, fingerprint FROM chunks WHERE note_id = ?", (note_id,)
            ).fetchall()
        }
        for chunk in chunks:
            row = existing.pop(chunk.seq, None)
            if row is not None and str(row["fingerprint"]) == chunk.fingerprint:
                conn.execute("UPDATE chunks SET ref = ? WHERE id = ?", (permalink, row["id"]))
                continue
            if row is not None:
                self._drop_vector(int(row["id"]))
                conn.execute(
                    "UPDATE chunks SET ref=?, fingerprint=?, text=?, state='pending', attempts=0 "
                    "WHERE id=?",
                    (permalink, chunk.fingerprint, chunk.text, int(row["id"])),
                )
                continue
            self._insert_chunk(note_id, permalink, chunk)
        for row in existing.values():
            self._drop_vector(int(row["id"]))
            conn.execute("DELETE FROM chunks WHERE id = ?", (int(row["id"]),))

    def _insert_chunk(self, note_id: int, permalink: str, chunk: Chunk) -> None:
        self._db.conn.execute(
            "INSERT INTO chunks(note_id, seq, ref, fingerprint, text, state) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (note_id, chunk.seq, permalink, chunk.fingerprint, chunk.text),
        )

    def _drop_vector(self, chunk_id: int) -> None:
        if not self._db.has_vec_table():
            return
        try:
            self._db.conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (chunk_id,))
        except sqlite3.Error:  # pragma: no cover - vec table vanished
            logger.debug("could not drop vector for chunk %s", chunk_id, exc_info=True)

    # ----------------------------------------------------------------- delete

    def _delete_note(self, path: str) -> bool:
        conn = self._db.conn
        row = conn.execute("SELECT id, permalink FROM notes WHERE path = ?", (path,)).fetchone()
        if row is None:
            return False
        note_id = int(row["id"])
        for chunk_row in conn.execute(
            "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
        ).fetchall():
            self._drop_vector(int(chunk_row["id"]))
        # search_rows explicitly (its delete trigger keeps FTS in sync);
        # the rest goes by ON DELETE CASCADE.
        conn.execute("DELETE FROM search_rows WHERE note_id = ?", (note_id,))
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._unresolve_target(str(row["permalink"]))
        return True


__all__ = ["IndexWriter"]
