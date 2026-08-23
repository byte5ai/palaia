"""The disposable projection: SQLite full-text, vector and hybrid search.

Files are the only truth (MASTERPLAN §5.1); everything in this package is
derived from them and may be deleted at any time. ``reindex`` rebuilds it from
files alone and must reproduce identical query results (format spec §10) —
that invariant, not the schema, is what this package promises.

Public surface (SPEC-104):

* :class:`VaultIndex` — one vault's index: lifecycle, incremental updates from
  SPEC-102 change events, hybrid search, embed backlog, status.
* :class:`IndexWriter` — the write side; also the doctor's ``ReindexSink`` and
  ``IndexView``, so ``reindex``/``verify`` plug straight into SPEC-102's
  doctor primitives.
* :class:`IndexSearch` — the three query modes and their rank fusion.
* :class:`EmbeddingConfig` / :class:`Embedder` — local embeddings, always off
  the write path (SPEC-003 measured 437 ms/note; see :mod:`.embeddings`).
* :class:`SearchFilters`, :class:`SearchHit`, :class:`SearchResults`,
  :class:`IndexStatus`, :class:`EmbedStatus` — the API's value types.
"""

from __future__ import annotations

from .db import INDEX_RELATIVE_PATH, IndexDatabase
from .embeddings import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    Chunk,
    Embedder,
    EmbedderUnavailableError,
    EmbeddingConfig,
    FastEmbedEmbedder,
    chunk_text,
    embeddable_text,
)
from .graph import (
    AccessStat,
    Direction,
    Edge,
    GraphReader,
    IndexedNote,
    IndexedObservation,
)
from .models import (
    EmbedStatus,
    HitKind,
    IndexStatus,
    SearchFilters,
    SearchHit,
    SearchMode,
    SearchResults,
    fingerprint,
    observation_permalink,
    relation_permalink,
)
from .schema import SCHEMA_VERSION
from .search import RRF_K, IndexSearch, fts_match_expression
from .service import VaultIndex
from .writer import IndexWriter

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_MODEL",
    "INDEX_RELATIVE_PATH",
    "RRF_K",
    "SCHEMA_VERSION",
    "AccessStat",
    "Chunk",
    "Direction",
    "Edge",
    "EmbedStatus",
    "Embedder",
    "EmbedderUnavailableError",
    "EmbeddingConfig",
    "FastEmbedEmbedder",
    "GraphReader",
    "HitKind",
    "IndexDatabase",
    "IndexSearch",
    "IndexStatus",
    "IndexWriter",
    "IndexedNote",
    "IndexedObservation",
    "SearchFilters",
    "SearchHit",
    "SearchMode",
    "SearchResults",
    "VaultIndex",
    "chunk_text",
    "embeddable_text",
    "fingerprint",
    "fts_match_expression",
    "observation_permalink",
    "relation_permalink",
]
