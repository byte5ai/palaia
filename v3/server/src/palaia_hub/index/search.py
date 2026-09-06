"""FTS, vector and hybrid querying over one vault's index.

**Query text is user input, not FTS5 syntax.** ``search("rate limit -42")``
must not blow up on FTS5's operators, so the query is tokenized with the same
character classes the ``unicode61`` tokenizer uses and rebuilt as
``"rate" AND "limit" AND "42"``. Callers never need to know FTS5 exists; a
query whose every token is punctuation matches nothing, which is a result too.

**Fusion is reciprocal rank fusion**, not score addition. The spike's sketch
summed ``1/(rank+1)`` per list, which is RRF with ``k=1`` — steep enough that
the top FTS hit almost always wins outright. ``k=60`` (the value the RRF paper
settles on) keeps a result that both lists rank *moderately* well ahead of one
that only one list loves, which is the entire point of hybridizing: BM25 finds
the exact words, vectors find the paraphrase, and agreement is the signal.

**Degradation is explicit.** Vectors arrive asynchronously (see
:mod:`.embeddings`), so a hybrid query issued while the backlog drains has no
vector list to fuse. It answers from FTS and sets
:attr:`~.models.SearchResults.degraded`, rather than silently pretending the
vector half ran.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from .db import IndexDatabase
from .models import (
    SearchFilters,
    SearchHit,
    SearchMode,
    SearchResults,
)
from .schema import KIND_NOTE

logger = logging.getLogger("palaia_hub.index.search")

#: RRF constant. 60 is the value from Cormack et al.'s original evaluation and
#: the de-facto default in hybrid-search implementations.
RRF_K = 60

#: KNN over-fetch (issue #361): several chunks of one note may crowd the
#: top-k, so the raw row count asked of sqlite-vec is ``limit`` times this
#: factor, and never below the minimum.
KNN_OVERFETCH_FACTOR = 8
KNN_MIN_ROWS = 40

#: Column weights for bm25(): a title match is worth much more than a body
#: match, matching the linear-scan adapter's 1.0-vs-0.5 intuition but ranked
#: rather than bucketed.
_BM25_TITLE_WEIGHT = 10.0
_BM25_TEXT_WEIGHT = 1.0

#: How many rows each half of a hybrid query fetches before fusion. Fusion can
#: promote a result ranked ~30th by one list, so both lists must be deeper than
#: the requested page.
_FUSION_DEPTH_FACTOR = 5
_FUSION_MIN_DEPTH = 30

#: Score scale for lexical-only results when the lexical pass was disjunctive
#: (``LEXICAL_TAIL`` fusion). Small enough that such a result always sorts
#: below every vector result while keeping its own BM25 order.
_TAIL_SCALE = 1e-3

#: The two fusion policies (see :meth:`IndexSearch.fuse`).
PEER = "peer"
LEXICAL_TAIL = "lexical-tail"

#: Tokens the ``unicode61`` tokenizer would produce: runs of alphanumerics,
#: underscore excluded (unicode61 treats it as a separator).
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def query_tokens(query: str) -> list[str]:
    """Tokenize a user query the way the FTS tokenizer will."""
    return _TOKEN_RE.findall(query.casefold())


def fts_match_expression(query: str, *, operator: str = "AND") -> str | None:
    """Build an FTS5 MATCH expression, or ``None`` if nothing is searchable."""
    tokens = query_tokens(query)
    if not tokens:
        return None
    return f" {operator} ".join(f'"{token}"' for token in tokens)


@dataclass(frozen=True, slots=True)
class _Clause:
    sql: str
    params: tuple[Any, ...]


def _filter_clause(filters: SearchFilters, alias: str = "n") -> _Clause:
    """Translate :class:`SearchFilters` into SQL over the ``notes`` alias."""
    parts: list[str] = []
    params: list[Any] = []
    if filters.scope:
        scope = filters.scope.strip("/")
        parts.append(f"({alias}.folder = ? OR {alias}.folder LIKE ?)")
        params.extend([scope, f"{scope}/%"])
    if filters.types:
        placeholders = ",".join("?" for _ in filters.types)
        parts.append(f"{alias}.type IN ({placeholders})")
        params.extend(filters.types)
    if filters.exclude_types:
        placeholders = ",".join("?" for _ in filters.exclude_types)
        parts.append(f"{alias}.type NOT IN ({placeholders})")
        params.extend(filters.exclude_types)
    if filters.since:
        parts.append(f"COALESCE({alias}.modified, {alias}.created, '') >= ?")
        params.append(filters.since)
    if filters.until:
        parts.append(f"COALESCE({alias}.modified, {alias}.created, '') <= ?")
        params.append(filters.until)
    for tag in filters.tags:
        parts.append(
            f"EXISTS (SELECT 1 FROM note_tags t WHERE t.note_id = {alias}.id AND t.tag = ?)"
        )
        params.append(tag.lower())
    for key, value in filters.meta:
        parts.append(
            f"EXISTS (SELECT 1 FROM note_meta m WHERE m.note_id = {alias}.id "
            f"AND m.key = ? AND m.value = ?)"
        )
        params.extend([key, value])
    if not parts:
        return _Clause("", ())
    return _Clause(" AND " + " AND ".join(parts), tuple(params))


def _no_vectors_reason(
    vectors_reason: str, query_embedding: Sequence[float] | None, filters: SearchFilters
) -> str:
    """Why a vector/hybrid query is being answered from full-text search.

    The caller's own reason (embeddings disabled, backlog not started, the
    query embedding failed) wins. Otherwise the KNN ran and found nothing:
    with a filter that means no note *matching the filter* has a vector yet
    — not that vectors as such are missing (issue #361).
    """
    if vectors_reason:
        return vectors_reason
    if query_embedding is None:
        return "no vectors are ready yet — the embed backlog is still draining"
    if _filter_clause(filters).sql:
        return (
            "none of the notes matching the filter has a vector yet — "
            "answering from full-text search"
        )
    return "the vector search matched nothing — answering from full-text search"


def _kind_clause(filters: SearchFilters, alias: str = "sr") -> _Clause:
    if not filters.kinds:
        return _Clause("", ())
    placeholders = ",".join("?" for _ in filters.kinds)
    return _Clause(f" AND {alias}.kind IN ({placeholders})", tuple(filters.kinds))


def _row_to_hit(
    row: sqlite3.Row,
    *,
    kind: str,
    snippet: str,
    score: float,
    fts_rank: int | None = None,
    vector_rank: int | None = None,
) -> SearchHit:
    return SearchHit(
        ref=str(row["ref"]),
        permalink=str(row["permalink"]),
        kind=kind,  # type: ignore[arg-type]
        title=str(row["title"]),
        snippet=snippet,
        score=score,
        path=str(row["path"]),
        type=str(row["type"]),
        tags=tuple(json.loads(str(row["tags"] or "[]"))),
        modified=str(row["modified"] or ""),
        fts_rank=fts_rank,
        vector_rank=vector_rank,
    )


class IndexSearch:
    """Read-side of the index: the three modes and their fusion."""

    def __init__(self, db: IndexDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------------- FTS

    def fts(
        self, query: str, *, limit: int = 10, filters: SearchFilters | None = None
    ) -> list[SearchHit]:
        """Rank rows by BM25 over the FTS5 index (see :meth:`fts_pass`)."""
        return self.fts_pass(query, limit=limit, filters=filters)[0]

    def fts_pass(
        self, query: str, *, limit: int = 10, filters: SearchFilters | None = None
    ) -> tuple[list[SearchHit], str]:
        """Rank rows by BM25, reporting which pass produced them.

        Two passes: every token required (precise — "rate limit" means both
        words), and if that finds nothing, any token (recall — a
        natural-language question like "what database backs the search layer"
        shares only some words with the note that answers it).

        The pass is returned because it is a statement about *evidence
        strength*: an ``AND`` hit contains everything the caller typed, an
        ``OR`` hit merely overlaps. Hybrid fusion weights the two differently
        (see :meth:`search`), which is the difference between a paraphrased
        question being answered and being buried under lexical near-misses.
        """
        for operator in ("AND", "OR"):
            match = fts_match_expression(query, operator=operator)
            if match is None:
                return [], operator
            hits = self._fts_match(match, limit=limit, filters=filters)
            if hits:
                return hits, operator
            if len(query_tokens(query)) < 2:
                break
        return [], "OR"

    def _fts_match(
        self, match: str, *, limit: int, filters: SearchFilters | None
    ) -> list[SearchHit]:
        filters = filters or SearchFilters()
        where = _filter_clause(filters)
        kinds = _kind_clause(filters)
        sql = (
            "SELECT sr.kind AS kind, sr.ref AS ref, sr.note_id AS note_id, "
            "n.permalink AS permalink, n.path AS path, n.type AS type, n.tags AS tags, "
            "n.modified AS modified, sr.title AS title, "
            "bm25(fts, ?, ?) AS bm25_score, "
            "snippet(fts, 1, '', '', '…', 14) AS snip "
            "FROM fts JOIN search_rows sr ON sr.id = fts.rowid "
            "JOIN notes n ON n.id = sr.note_id "
            "WHERE fts MATCH ?"
            f"{kinds.sql}{where.sql} "
            "ORDER BY bm25_score, sr.ref LIMIT ?"
        )
        params = (
            _BM25_TITLE_WEIGHT,
            _BM25_TEXT_WEIGHT,
            match,
            *kinds.params,
            *where.params,
            limit,
        )
        with self._db.lock:
            try:
                rows = self._db.conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                # A MATCH expression the tokenizer rejects is a bad query, not
                # a broken index: report nothing rather than raising at a
                # caller who typed something odd.
                logger.debug("FTS query rejected (%s): %r", exc, match)
                return []
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows):
            hits.append(
                _row_to_hit(
                    row,
                    kind=str(row["kind"]),
                    snippet=str(row["snip"] or "").strip(),
                    # bm25() returns a negative number, better = more negative.
                    score=-float(row["bm25_score"]),
                    fts_rank=rank,
                )
            )
        return hits

    # ---------------------------------------------------------------- vectors

    def vector(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[SearchHit]:
        """KNN over ready chunk vectors, folded to one hit per note."""
        if not self._db.vectors.available or not self._db.has_vec_table():
            return []
        import sqlite_vec

        filters = filters or SearchFilters()
        # Over-fetch: several chunks of one note may crowd the top-k, so the
        # raw k is generous.
        knn = max(limit * KNN_OVERFETCH_FACTOR, KNN_MIN_ROWS)
        serialized = sqlite_vec.serialize_float32(list(embedding))
        inner = _filter_clause(filters, "n2")
        if inner.sql:
            # Issue #361: the filter is applied *inside* the KNN — sqlite-vec
            # restricts the nearest-neighbour scan to `rowid IN (...)` — so a
            # narrow scope/type filter cannot empty the result merely by
            # dropping every over-fetched row after the fact.
            knn_sql = (
                "SELECT rowid, distance FROM vec_chunks WHERE embedding MATCH ? AND k = ? "
                "AND rowid IN (SELECT c2.id FROM chunks c2 JOIN notes n2 ON n2.id = c2.note_id "
                f"WHERE 1=1{inner.sql})"
            )
            params: tuple[Any, ...] = (serialized, knn, *inner.params)
        else:
            knn_sql = (
                "SELECT rowid, distance FROM vec_chunks "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
            )
            params = (serialized, knn)
        sql = (
            "SELECT c.note_id AS note_id, c.ref AS ref, c.text AS chunk_text, v.distance AS dist, "
            "n.permalink AS permalink, n.path AS path, n.type AS type, n.tags AS tags, "
            "n.modified AS modified, n.title AS title "
            f"FROM ({knn_sql}) v "
            "JOIN chunks c ON c.id = v.rowid "
            "JOIN notes n ON n.id = c.note_id "
            "ORDER BY v.distance, c.ref"
        )
        with self._db.lock:
            try:
                rows = self._db.conn.execute(sql, params).fetchall()
            except sqlite3.Error as exc:  # pragma: no cover - vec table issues
                logger.warning("vector query failed, degrading to FTS: %s", exc)
                return []

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for row in rows:
            permalink = str(row["permalink"])
            if permalink in seen:
                continue
            seen.add(permalink)
            distance = float(row["dist"])
            hits.append(
                _row_to_hit(
                    row,
                    kind=KIND_NOTE,
                    snippet=_head(str(row["chunk_text"])),
                    score=1.0 / (1.0 + distance),
                    vector_rank=len(hits),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    # ----------------------------------------------------------------- hybrid

    def fuse(
        self,
        fts_hits: Sequence[SearchHit],
        vector_hits: Sequence[SearchHit],
        *,
        limit: int = 10,
        policy: str = PEER,
    ) -> list[SearchHit]:
        """Rank-fuse the two lists, keyed by note permalink.

        Fusion is per *note*: a note whose observation matched textually and
        whose body matched semantically is one result, not two. The surviving
        ``ref`` is the best-ranked FTS row for that note — often an
        observation's synthetic permalink, which is the addressable thing the
        caller can act on — and falls back to the note-level vector hit when
        only the vector list found it.

        **Each list is collapsed to one entry per note before ranks are
        taken.** The FTS side returns *rows*, and a note can easily contribute
        six of them (its body plus five observations). Scoring each row
        separately would hand that note six reciprocal-rank contributions and
        let sheer row count outrank genuine agreement between the two
        retrievers — measured on the golden vault, that alone dropped hybrid
        recall@5 below plain FTS. Rank means "this note was the n-th best
        answer according to this retriever", nothing else.

        **Two policies.** ``PEER`` is symmetric RRF: both retrievers are
        credible judges, and agreement between them wins. That is right when
        the lexical list came from the conjunctive pass — those documents
        contain everything the caller typed.

        ``LEXICAL_TAIL`` applies when no document contained all the query
        terms and the lexical list is the disjunctive fallback. Then lexical
        search has no real evidence, only word overlap, and symmetric RRF
        actively hurts: a note both lists rank *mediocrely* outscores the note
        the vector retriever ranks first, because under RRF (k=60) mere
        agreement beats any single-list rank. Measured on the golden vault's
        relevance battery, that is exactly how a paraphrased question's correct
        answer fell from vector rank 1 to hybrid rank 6. So under this policy
        the vector ranking leads and lexical-only hits are appended below it —
        candidates, not competitors.
        """
        fts_ranked = _collapse(fts_hits)
        vector_ranked = _collapse(vector_hits)
        scores: dict[str, float] = {}
        best: dict[str, SearchHit] = {}
        fts_weight = 1.0 if policy == PEER else _TAIL_SCALE
        fts_rank_of: dict[str, int] = {}
        vector_rank_of: dict[str, int] = {}
        for rank, hit in enumerate(fts_ranked):
            scores[hit.permalink] = scores.get(hit.permalink, 0.0) + fts_weight / (RRF_K + rank + 1)
            best[hit.permalink] = hit
            fts_rank_of[hit.permalink] = rank
        for rank, hit in enumerate(vector_ranked):
            scores[hit.permalink] = scores.get(hit.permalink, 0.0) + 1.0 / (RRF_K + rank + 1)
            vector_rank_of[hit.permalink] = rank
            if hit.permalink not in best:
                best[hit.permalink] = hit
            elif not best[hit.permalink].snippet:
                best[hit.permalink] = replace(best[hit.permalink], snippet=hit.snippet)
        ordered = sorted(
            best.values(),
            key=lambda hit: (-scores[hit.permalink], hit.ref),
        )
        return [
            replace(
                hit,
                score=scores[hit.permalink],
                fts_rank=fts_rank_of.get(hit.permalink),
                vector_rank=vector_rank_of.get(hit.permalink),
            )
            for hit in ordered[:limit]
        ]

    def search(
        self,
        query: str,
        *,
        mode: SearchMode = "hybrid",
        limit: int = 10,
        filters: SearchFilters | None = None,
        query_embedding: Sequence[float] | None = None,
        vectors_reason: str = "",
    ) -> SearchResults:
        """Run ``query`` in ``mode``, degrading to FTS when vectors cannot run."""
        filters = filters or SearchFilters()
        depth = max(limit * _FUSION_DEPTH_FACTOR, _FUSION_MIN_DEPTH)

        if mode == "fts":
            return SearchResults(
                hits=tuple(self.fts(query, limit=limit, filters=filters)),
                mode=mode,
                effective_mode="fts",
            )

        vector_hits: list[SearchHit] = []
        if query_embedding is not None:
            vector_hits = self.vector(query_embedding, limit=depth, filters=filters)

        if mode == "vector":
            if query_embedding is None or not vector_hits:
                reason = _no_vectors_reason(vectors_reason, query_embedding, filters)
                return SearchResults(
                    hits=tuple(self._degraded_fts(query, limit=limit, filters=filters)),
                    mode=mode,
                    effective_mode="fts",
                    degraded=True,
                    degraded_reason=reason,
                )
            return SearchResults(
                hits=tuple(vector_hits[:limit]), mode=mode, effective_mode="vector"
            )

        fts_hits, fts_operator = self.fts_pass(query, limit=depth, filters=filters)
        if not vector_hits:
            return SearchResults(
                hits=tuple(_collapse(fts_hits)[:limit]),
                mode=mode,
                effective_mode="fts",
                degraded=True,
                degraded_reason=_no_vectors_reason(vectors_reason, query_embedding, filters),
            )
        return SearchResults(
            hits=tuple(
                self.fuse(
                    fts_hits,
                    vector_hits,
                    limit=limit,
                    policy=PEER if fts_operator == "AND" else LEXICAL_TAIL,
                )
            ),
            mode=mode,
            effective_mode="hybrid",
        )

    def _degraded_fts(
        self, query: str, *, limit: int, filters: SearchFilters | None
    ) -> list[SearchHit]:
        """FTS results at *note* granularity, for a degraded hybrid/vector query.

        A hybrid query's results are one-per-note (that is what fusion
        produces), so its FTS fallback must be too — otherwise ``limit=5``
        silently means "five matching lines, possibly all from one note".
        Explicit ``mode="fts"`` keeps sub-note rows: there the caller asked for
        the addressable granularity.
        """
        depth = max(limit * _FUSION_DEPTH_FACTOR, _FUSION_MIN_DEPTH)
        return _collapse(self.fts(query, limit=depth, filters=filters))[:limit]


def _collapse(hits: Sequence[SearchHit]) -> list[SearchHit]:
    """One entry per note, keeping each note's best-ranked hit and order."""
    seen: set[str] = set()
    collapsed: list[SearchHit] = []
    for hit in hits:
        if hit.permalink in seen:
            continue
        seen.add(hit.permalink)
        collapsed.append(hit)
    return collapsed


def _head(text: str, width: int = 160) -> str:
    """First ``width`` characters of a chunk, as a vector hit's snippet."""
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "…"


__all__ = [
    "LEXICAL_TAIL",
    "PEER",
    "RRF_K",
    "IndexSearch",
    "fts_match_expression",
    "query_tokens",
]
