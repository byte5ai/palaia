"""Rank fusion, pinned as a unit — no database, no model.

The two properties that took measurement to get right (see
``test_hybrid_relevance.py``): a note is ranked once no matter how many rows
it matched, and a disjunctive lexical list never outranks the vector list.
"""

from __future__ import annotations

from palaia_hub.index import IndexSearch, SearchHit
from palaia_hub.index.search import LEXICAL_TAIL, PEER


def _hit(permalink: str, ref: str | None = None, kind: str = "note") -> SearchHit:
    return SearchHit(
        ref=ref or permalink,
        permalink=permalink,
        kind=kind,  # type: ignore[arg-type]
        title=permalink,
        snippet="",
        score=0.0,
    )


def _fuse(fts: list[SearchHit], vector: list[SearchHit], **kwargs: object) -> list[str]:
    searcher = IndexSearch.__new__(IndexSearch)  # no DB needed for pure fusion
    hits = searcher.fuse(fts, vector, limit=10, **kwargs)  # type: ignore[arg-type]
    return [hit.permalink for hit in hits]


def test_agreement_between_retrievers_wins_under_peer_policy() -> None:
    fts = [_hit("a"), _hit("b"), _hit("c")]
    vector = [_hit("c"), _hit("d")]
    # "c" is the only note both retrievers found: it leads even though each
    # list ranks something else higher.
    assert _fuse(fts, vector, policy=PEER)[0] == "c"


def test_many_matching_rows_do_not_stack_a_notes_score() -> None:
    """A note with six matching observations is still one ranked answer."""
    fts = [_hit("noisy", f"noisy/obs/cat/{n:08x}", "observation") for n in range(6)]
    fts.append(_hit("precise"))
    vector = [_hit("precise")]
    assert _fuse(fts, vector, policy=PEER)[0] == "precise"


def test_lexical_tail_policy_lets_the_vector_ranking_lead() -> None:
    fts = [_hit("overlap-noise"), _hit("more-noise"), _hit("agreed")]
    vector = [_hit("semantic-answer"), _hit("agreed")]
    ranked = _fuse(fts, vector, policy=LEXICAL_TAIL)
    assert ranked[0] == "semantic-answer"
    assert ranked[1] == "agreed"
    # Lexical-only hits keep their BM25 order, below every vector result.
    assert ranked[2:] == ["overlap-noise", "more-noise"]


def test_fusion_keeps_the_more_specific_ref_from_the_lexical_list() -> None:
    fts = [_hit("note", "note/obs/decision/deadbeef", "observation")]
    vector = [_hit("note")]
    searcher = IndexSearch.__new__(IndexSearch)
    fused = searcher.fuse(fts, vector, limit=5)
    assert fused[0].ref == "note/obs/decision/deadbeef"
    assert fused[0].kind == "observation"
    # Both retrievers' ranks survive on the result, for debugging a ranking.
    assert fused[0].vector_rank == 0


def test_empty_lists_fuse_to_nothing() -> None:
    assert _fuse([], []) == []
    assert _fuse([_hit("a")], []) == ["a"]
    assert _fuse([], [_hit("b")]) == ["b"]
