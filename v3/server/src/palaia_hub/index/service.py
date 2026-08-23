"""The per-vault index as one object: :class:`VaultIndex`.

Everything the rest of the hub touches goes through here — the gateway's
search tool, the dashboard's status panel, the doctor's reindex/verify.
Three responsibilities:

1. **Lifecycle.** Open the SQLite file, do the initial build, subscribe to the
   vault's change events, and stop cleanly. The subscription is what makes the
   index incremental: SPEC-102's :class:`~palaia_hub.vault.EventBus` already
   emits exactly the vocabulary needed (created/modified/moved/deleted/renamed).
2. **The embed backlog.** A background task drains pending chunks in batches.
   It is deliberately the *only* thing that ever calls an embedder for
   indexing, so no write path can accidentally take the 437 ms/note hit the
   SPEC-003 spike measured.
3. **Degrading honestly.** Every query reports the mode it actually ran in.
   With no embedder, no sqlite-vec, or an undrained backlog, a hybrid query is
   an FTS query that says so.

An :class:`EntityRenamed` event triggers a full reindex rather than a
single-note update: a rename rewrites *inbound wikilinks across the whole
vault* in one commit (format spec §4.2) and emits one event for all of it, so
the only correct response is to re-walk the vault. That is affordable because
:meth:`VaultIndex.reindex` skips notes whose checksum is unchanged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from palaia_hub.vault import (
    ChangeEvent,
    EntityRenamed,
    Finding,
    IndexEntry,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
    VaultDoctor,
    VaultEngine,
)

from .db import INDEX_RELATIVE_PATH, IndexDatabase
from .embeddings import Embedder, EmbedderUnavailableError, EmbeddingConfig, build_embedder
from .graph import GraphReader
from .models import (
    EmbedStatus,
    IndexStatus,
    SearchFilters,
    SearchMode,
    SearchResults,
)
from .schema import META_EMBED_DIM, META_EMBED_MODEL, SCHEMA_VERSION
from .search import IndexSearch
from .writer import IndexWriter

logger = logging.getLogger("palaia_hub.index.service")

#: How long the embed worker waits for new work before re-checking. Only a
#: safety net — every indexing write wakes it immediately.
_WORKER_POLL_SECONDS = 2.0

#: A chunk that fails this many times is parked as ``failed`` instead of
#: spinning the worker forever on the same input.
_MAX_EMBED_ATTEMPTS = 3


class VaultIndex:
    """One vault's searchable projection."""

    def __init__(
        self,
        engine: VaultEngine,
        *,
        path: Path | None = None,
        embedding: EmbeddingConfig | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._engine = engine
        self._embedding = embedding or EmbeddingConfig()
        self.db = IndexDatabase(path or engine.root / INDEX_RELATIVE_PATH, engine.name)
        self.writer = IndexWriter(self.db, self._embedding)
        self.searcher = IndexSearch(self.db)
        #: Identity/graph/access reads the recall layer (SPEC-106) needs on
        #: top of :attr:`searcher`. Same database, different question shape.
        self.graph = GraphReader(self.db)
        self._doctor = VaultDoctor(engine)
        self._embedder: Embedder | None = embedder
        self._embedder_failed = ""
        self._embedder_probed = embedder is not None
        self._unsubscribe: Callable[[], None] | None = None
        self._worker: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._closing = False
        self._last_indexed_at = 0.0

    # ------------------------------------------------------------- lifecycle

    async def open(self, *, build: bool = True, start_worker: bool = True) -> int:
        """Open the index, optionally build it, and subscribe to change events.

        Returns the number of notes indexed by the initial build (0 when
        ``build=False``).
        """
        await asyncio.to_thread(self.db.open)
        indexed = await self.reindex() if build else 0
        if self._engine.bus is not None:
            self._unsubscribe = self._engine.bus.subscribe(self._on_event)
        if start_worker and self._embedding.enabled:
            self.start_worker()
        return indexed

    def start_worker(self) -> None:
        """Start the background embed worker (idempotent)."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def close(self) -> None:
        """Unsubscribe, stop the worker, close the database."""
        self._closing = True
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._unsubscribe = None
        if self._worker is not None:
            self._wake.set()
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        await asyncio.to_thread(self.db.close)

    # -------------------------------------------------------- doctor plumbing

    def index_entries(self) -> Iterator[IndexEntry]:
        """:class:`~palaia_hub.vault.IndexView` implementation (drift check)."""
        return self.writer.index_entries()

    async def reindex(self) -> int:
        """Full rebuild from files via the doctor's reindex hook.

        The whole walk is one transaction (see :class:`~.writer.IndexWriter`),
        and notes whose checksum already matches the index are skipped, so a
        no-op reindex is cheap enough to use as the response to any event the
        index cannot interpret precisely.
        """
        count = await self._engine.reindex(self.writer)
        self._last_indexed_at = time.monotonic()
        self._wake.set()
        logger.debug("reindexed %d note(s) of vault %s", count, self._engine.name)
        return count

    async def verify(self) -> list[Finding]:
        """Doctor verification *including* file↔index drift for this index."""
        return await self._doctor.verify(self)

    # ------------------------------------------------------------ event intake

    async def _on_event(self, event: ChangeEvent) -> None:
        """Apply one vault change event to the index."""
        try:
            await self.apply_event(event)
        except Exception:  # noqa: BLE001 - an index update must not break a write
            logger.exception("index update failed", extra={"event": type(event).__name__})

    async def apply_event(self, event: ChangeEvent) -> None:
        """Apply one change event (public so tests can drive it directly)."""
        if isinstance(event, NoteDeleted):
            await asyncio.to_thread(self.writer.delete_note, event.path)
        elif isinstance(event, NoteMoved):
            note = await self._engine.read_note(event.path)
            await asyncio.to_thread(self.writer.move_note, event.previous_path, note)
        elif isinstance(event, (NoteCreated, NoteModified)):
            note = await self._engine.read_note(event.path)
            await asyncio.to_thread(self.writer.upsert_note, note)
        elif isinstance(event, EntityRenamed):
            # A rename rewrote inbound links vault-wide under a single event.
            await self.reindex()
        else:  # pragma: no cover - the union is closed today
            logger.debug("ignoring unknown event %s", type(event).__name__)
            return
        self._last_indexed_at = time.monotonic()
        self._wake.set()

    # ----------------------------------------------------------------- search

    async def search(
        self,
        query: str,
        *,
        mode: SearchMode = "hybrid",
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> SearchResults:
        """Search this vault. Never raises on odd query text."""
        embedding: Sequence[float] | None = None
        reason = ""
        if mode in ("vector", "hybrid"):
            embedding, reason = await self._embed_query(query)
        return await asyncio.to_thread(
            lambda: self.searcher.search(
                query,
                mode=mode,
                limit=limit,
                filters=filters,
                query_embedding=embedding,
                vectors_reason=reason,
            )
        )

    async def _embed_query(self, query: str) -> tuple[Sequence[float] | None, str]:
        """Embed the query, or explain why the vector half cannot run.

        Deliberately checks the backlog *before* paying for a query embedding
        (~108 ms in the spike): with nothing ready to match against, the
        embedding would be wasted work on the answer path.
        """
        status = self.embed_status()
        if not status.enabled:
            return None, "embeddings are disabled for this vault"
        if not status.available:
            return None, status.reason or "no embedding backend is available"
        if status.ready == 0:
            return None, (
                f"no vectors are ready yet ({status.pending} chunk(s) pending) — "
                f"answering from full-text search"
            )
        embedder = await self._ensure_embedder()
        if embedder is None:
            return None, self._embedder_failed or "no embedding backend is available"
        try:
            vectors = await asyncio.to_thread(embedder.embed, [query])
        except Exception as exc:  # noqa: BLE001 - backend-specific failures
            logger.warning("query embedding failed, degrading to FTS: %s", exc)
            return None, f"query embedding failed ({exc})"
        return vectors[0], ""

    # ------------------------------------------------------------- embeddings

    async def _ensure_embedder(self) -> Embedder | None:
        if self._embedder is not None:
            return self._embedder
        if self._embedder_probed:
            return None
        self._embedder_probed = True
        try:
            embedder = await asyncio.to_thread(build_embedder, self._embedding)
        except EmbedderUnavailableError as exc:
            self._embedder_failed = str(exc)
            logger.warning("embeddings unavailable: %s", exc)
            return None
        self._embedder = embedder
        self.db.meta_set(META_EMBED_MODEL, embedder.name)
        self.db.meta_set(META_EMBED_DIM, str(embedder.dim))
        return embedder

    async def _worker_loop(self) -> None:
        """Drain the embed backlog in batches, forever."""
        while not self._closing:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=_WORKER_POLL_SECONDS)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                while await self.embed_next_batch():
                    pass
            except asyncio.CancelledError:  # pragma: no cover - shutdown
                raise
            except Exception:  # noqa: BLE001 - the worker must survive anything
                logger.exception("embed worker batch failed")
                await asyncio.sleep(_WORKER_POLL_SECONDS)

    async def embed_next_batch(self) -> int:
        """Embed one batch of pending chunks; returns how many were embedded.

        Public because it is also how tests (and a future CLI ``palaia-hub
        index embed``) drain the backlog deterministically instead of racing
        the worker.
        """
        if not self._embedding.enabled:
            return 0
        rows = await asyncio.to_thread(self._claim_batch)
        if not rows:
            return 0
        embedder = await self._ensure_embedder()
        if embedder is None:
            return 0
        if not await asyncio.to_thread(self.db.ensure_vec_table, embedder.dim):
            logger.info(
                "vector table unavailable (%s); backlog left pending", self.db.vectors.reason
            )
            return 0
        texts = [text for _, text in rows]
        try:
            vectors = await asyncio.to_thread(embedder.embed, texts)
        except Exception as exc:  # noqa: BLE001 - backend-specific failures
            logger.warning("embedding batch failed: %s", exc)
            await asyncio.to_thread(self._record_failures, [chunk_id for chunk_id, _ in rows])
            return 0
        await asyncio.to_thread(
            self._store_vectors, [chunk_id for chunk_id, _ in rows], vectors
        )
        return len(rows)

    async def drain_embeddings(self, *, timeout: float = 120.0) -> int:
        """Embed everything pending (test/CLI helper); returns chunks embedded."""
        deadline = time.monotonic() + timeout
        total = 0
        while time.monotonic() < deadline:
            done = await self.embed_next_batch()
            if done == 0:
                break
            total += done
        return total

    def _claim_batch(self) -> list[tuple[int, str]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT id, text FROM chunks WHERE state = 'pending' "
                "ORDER BY id LIMIT ?",
                (self._embedding.batch_size,),
            ).fetchall()
        return [(int(row["id"]), str(row["text"])) for row in rows]

    def _store_vectors(self, chunk_ids: Sequence[int], vectors: Sequence[Sequence[float]]) -> None:
        import sqlite_vec

        with self.db.lock:
            conn = self.db.conn
            for chunk_id, vector in zip(chunk_ids, vectors, strict=True):
                conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (chunk_id,))
                conn.execute(
                    "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                    (chunk_id, sqlite_vec.serialize_float32(list(vector))),
                )
                conn.execute(
                    "UPDATE chunks SET state = 'ready', attempts = 0 WHERE id = ?", (chunk_id,)
                )
            conn.commit()

    def _record_failures(self, chunk_ids: Sequence[int]) -> None:
        with self.db.lock:
            conn = self.db.conn
            for chunk_id in chunk_ids:
                conn.execute(
                    "UPDATE chunks SET attempts = attempts + 1, "
                    "state = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END "
                    "WHERE id = ?",
                    (_MAX_EMBED_ATTEMPTS, chunk_id),
                )
            conn.commit()

    # ----------------------------------------------------------------- status

    def embed_status(self) -> EmbedStatus:
        """The embed backlog, as the status API reports it."""
        counts = {"pending": 0, "ready": 0, "failed": 0}
        if self.db.opened:
            with self.db.lock:
                for row in self.db.conn.execute(
                    "SELECT state, COUNT(*) AS n FROM chunks GROUP BY state"
                ).fetchall():
                    counts[str(row["state"])] = int(row["n"])
        available = self.db.vectors.available
        reason = "" if available else self.db.vectors.reason
        if available and self._embedder_failed:
            available = False
            reason = self._embedder_failed
        model = self.db.meta_get(META_EMBED_MODEL) or self._embedding.model
        dim = self.db.meta_get(META_EMBED_DIM)
        return EmbedStatus(
            enabled=self._embedding.enabled,
            available=available,
            model=model,
            dim=int(dim) if dim else 0,
            total=sum(counts.values()),
            ready=counts["ready"],
            pending=counts["pending"],
            failed=counts["failed"],
            reason=reason,
        )

    def status(self) -> IndexStatus:
        """Everything the dashboard/CLI needs about this vault's index."""
        with self.db.lock:
            conn = self.db.conn
            notes = int(conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"])
            observations = int(
                conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]
            )
            relations = int(conn.execute("SELECT COUNT(*) AS n FROM relations").fetchone()["n"])
            unresolved = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM relations WHERE target_permalink IS NULL"
                ).fetchone()["n"]
            )
            by_type = {
                str(row["type"]): int(row["n"])
                for row in conn.execute(
                    "SELECT type, COUNT(*) AS n FROM notes GROUP BY type ORDER BY type"
                ).fetchall()
            }
        return IndexStatus(
            vault=self._engine.name,
            path=str(self.db.path),
            schema_version=SCHEMA_VERSION,
            notes=notes,
            observations=observations,
            relations=relations,
            unresolved_relations=unresolved,
            embeds=self.embed_status(),
            counts_by_type=by_type,
        )


__all__ = ["VaultIndex"]
