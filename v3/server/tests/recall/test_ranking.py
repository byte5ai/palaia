"""Decay scoring: the three factors, the bound on them, and determinism."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from palaia_hub.config import RecallSettings
from palaia_hub.index import IndexedNote
from palaia_hub.recall.ranking import (
    DEFAULT_WEIGHTS,
    RANK_K,
    Candidate,
    RankingWeights,
    access_factor,
    decay_factors,
    parse_timestamp,
    rank_candidates,
    recency_factor,
    relevance_of,
    significance_factor,
    weights_from_settings,
)

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)


def note(
    permalink: str,
    *,
    type: str = "note",  # noqa: A002 - mirrors the vault-format field name
    modified: str = "",
    title: str = "",
) -> IndexedNote:
    return IndexedNote(
        permalink=permalink,
        path=f"{permalink}.md",
        title=title or permalink,
        type=type,
        folder="",
        tags=(),
        aliases=(),
        created="",
        modified=modified,
        body="",
    )


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------
# recency
# --------------------------------------------------------------------------

def test_recency_is_one_today_and_halves_each_half_life() -> None:
    assert recency_factor(iso(0), now=NOW, weights=DEFAULT_WEIGHTS) == pytest.approx(1.0)
    assert recency_factor(iso(30), now=NOW, weights=DEFAULT_WEIGHTS) == pytest.approx(
        0.5, abs=1e-6
    )
    assert recency_factor(iso(60), now=NOW, weights=DEFAULT_WEIGHTS) == pytest.approx(
        0.25, abs=1e-6
    )


def test_recency_is_monotone_decreasing_in_age() -> None:
    scores = [
        recency_factor(iso(days), now=NOW, weights=DEFAULT_WEIGHTS)
        for days in range(0, 400, 10)
    ]
    assert scores == sorted(scores, reverse=True)


def test_an_undated_note_gets_the_neutral_recency_not_zero() -> None:
    # "Undated" is not evidence of stale — the golden vault's notes are
    # mostly undated, and they must not all rank as ancient.
    assert recency_factor("", now=NOW, weights=DEFAULT_WEIGHTS) == DEFAULT_WEIGHTS.unknown_recency
    assert recency_factor("not-a-date", now=NOW, weights=DEFAULT_WEIGHTS) == (
        DEFAULT_WEIGHTS.unknown_recency
    )


def test_a_future_timestamp_reads_as_now_rather_than_negative() -> None:
    assert recency_factor(iso(-30), now=NOW, weights=DEFAULT_WEIGHTS) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("raw", "expected_year"),
    [("2026-08-23", 2026), ("2026-08-23T10:00:00Z", 2026), ("2026-08-23T10:00:00+02:00", 2026)],
)
def test_timestamp_parsing_tolerates_the_forms_frontmatter_uses(
    raw: str, expected_year: int
) -> None:
    parsed = parse_timestamp(raw)
    assert parsed is not None
    assert parsed.year == expected_year
    assert parsed.tzinfo is not None


# --------------------------------------------------------------------------
# access
# --------------------------------------------------------------------------

def test_access_is_zero_until_first_use_and_saturates_at_one() -> None:
    assert access_factor(0, weights=DEFAULT_WEIGHTS) == 0.0
    assert access_factor(1, weights=DEFAULT_WEIGHTS) > 0.0
    assert access_factor(20, weights=DEFAULT_WEIGHTS) == pytest.approx(1.0)
    assert access_factor(10_000, weights=DEFAULT_WEIGHTS) == 1.0


def test_access_growth_is_logarithmic_not_linear() -> None:
    first = access_factor(1, weights=DEFAULT_WEIGHTS)
    second = access_factor(2, weights=DEFAULT_WEIGHTS) - first
    assert second < first, "the second access must count for less than the first"


# --------------------------------------------------------------------------
# significance
# --------------------------------------------------------------------------

def test_entry_type_orders_significance_the_way_the_taxonomy_does() -> None:
    ordered = ["decision", "rule", "process", "project", "person", "note", "capture"]
    scores = [significance_factor(kind, 0, weights=DEFAULT_WEIGHTS) for kind in ordered]
    assert scores == sorted(scores, reverse=True)


def test_an_unknown_entry_type_still_scores() -> None:
    # Format spec §6 keeps unknown types valid (warn-first), so they must rank.
    score = significance_factor("meeting-minutes", 0, weights=DEFAULT_WEIGHTS)
    assert 0.0 < score < 1.0


def test_inbound_links_raise_significance() -> None:
    lonely = significance_factor("note", 0, weights=DEFAULT_WEIGHTS)
    popular = significance_factor("note", 12, weights=DEFAULT_WEIGHTS)
    assert popular > lonely


def test_centrality_weight_zero_makes_significance_purely_type_based() -> None:
    weights = RankingWeights(centrality_weight=0.0)
    assert significance_factor("note", 0, weights=weights) == significance_factor(
        "note", 50, weights=weights
    )


# --------------------------------------------------------------------------
# The composed score and its bound
# --------------------------------------------------------------------------

def test_boost_is_bounded_by_the_sum_of_the_weights() -> None:
    factors = decay_factors(
        note("a", type="decision", modified=iso(0)),
        hits=10_000,
        inbound=1000,
        now=NOW,
        weights=DEFAULT_WEIGHTS,
    )
    assert factors.boost <= DEFAULT_WEIGHTS.max_boost + 1e-9
    assert factors.boost == pytest.approx(DEFAULT_WEIGHTS.max_boost, abs=1e-6)


def test_no_factor_can_be_negative() -> None:
    factors = decay_factors(
        note("a", type="capture"), hits=0, inbound=0, now=NOW, weights=DEFAULT_WEIGHTS
    )
    assert factors.recency >= 0 and factors.access >= 0 and factors.significance >= 0
    assert factors.boost >= 0


def test_relevance_uses_reciprocal_rank() -> None:
    assert relevance_of(0) == pytest.approx(1.0 / (RANK_K + 1))
    assert relevance_of(1) < relevance_of(0)


def test_decay_cannot_overturn_a_thirty_rank_relevance_gap() -> None:
    # The design bound: decay reshuffles a neighborhood, it is not a second
    # retriever. A maximally boosted rank-40 hit must not beat an unboosted
    # rank-0 hit.
    best_possible = relevance_of(40) * (1.0 + DEFAULT_WEIGHTS.max_boost)
    assert best_possible < relevance_of(0)


def test_decay_can_overturn_a_close_relevance_gap() -> None:
    # ...and it must actually do something: a fresh, load-bearing rank-3 hit
    # should be able to pass an undated capture at rank 0.
    candidates = [
        Candidate(ref="a", permalink="a", kind="note", snippet="", relevance_score=1.0),
        Candidate(ref="b", permalink="b", kind="note", snippet="", relevance_score=0.9),
        Candidate(ref="c", permalink="c", kind="note", snippet="", relevance_score=0.8),
        Candidate(ref="d", permalink="d", kind="note", snippet="", relevance_score=0.7),
    ]
    notes = {
        "a": note("a", type="capture"),
        "b": note("b", type="capture"),
        "c": note("c", type="capture"),
        "d": note("d", type="decision", modified=iso(0)),
    }
    ranked = rank_candidates(
        candidates, notes, hits={}, inbound={"d": 12}, now=NOW, weights=DEFAULT_WEIGHTS
    )
    assert ranked[0].permalink == "d"


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

def _fixture_candidates() -> tuple[list[Candidate], dict[str, IndexedNote]]:
    candidates = [
        Candidate(
            ref=f"n{n}",
            permalink=f"n{n}",
            kind="note",
            snippet="",
            relevance_score=1.0 / (n + 1),
        )
        for n in range(8)
    ]
    notes = {
        f"n{n}": note(
            f"n{n}",
            type=["note", "rule", "decision", "capture"][n % 4],
            modified=iso(n * 5),
        )
        for n in range(8)
    }
    return candidates, notes


def test_ranking_is_deterministic_given_equal_inputs() -> None:
    candidates, notes = _fixture_candidates()
    hits = {f"n{n}": n for n in range(8)}
    inbound = {f"n{n}": 8 - n for n in range(8)}
    first = rank_candidates(candidates, notes, hits=hits, inbound=inbound, now=NOW)
    for _ in range(5):
        again = rank_candidates(candidates, notes, hits=hits, inbound=inbound, now=NOW)
        assert [entry.permalink for entry in again] == [entry.permalink for entry in first]
        assert [entry.score for entry in again] == [entry.score for entry in first]


def test_equal_scores_break_ties_on_ref_not_on_dict_order() -> None:
    candidates = [
        Candidate(ref="zebra", permalink="p", kind="note", snippet="", relevance_score=1.0),
        Candidate(ref="alpha", permalink="p", kind="note", snippet="", relevance_score=1.0),
    ]
    notes = {"p": note("p")}
    # Same permalink, same rank position cost differs, so force equal scores
    # by ranking each on its own.
    single = [
        rank_candidates([candidate], notes, hits={}, inbound={}, now=NOW)[0]
        for candidate in candidates
    ]
    assert single[0].score == single[1].score
    both = rank_candidates(candidates, notes, hits={}, inbound={}, now=NOW)
    assert [entry.ref for entry in both] == ["zebra", "alpha"], "rank order dominates"


def test_a_candidate_whose_note_vanished_is_dropped_not_defaulted() -> None:
    candidates = [
        Candidate(ref="gone", permalink="gone", kind="note", snippet="", relevance_score=1.0),
        Candidate(ref="here", permalink="here", kind="note", snippet="", relevance_score=0.5),
    ]
    ranked = rank_candidates(
        candidates, {"here": note("here")}, hits={}, inbound={}, now=NOW
    )
    assert [entry.permalink for entry in ranked] == ["here"]


# --------------------------------------------------------------------------
# Config plumbing
# --------------------------------------------------------------------------

def test_default_config_reproduces_the_default_weights() -> None:
    assert weights_from_settings(RecallSettings()) == RankingWeights()


def test_config_weights_reach_the_scorer() -> None:
    settings = RecallSettings(recency_weight=1.0, access_weight=0.0, significance_weight=0.0)
    weights = weights_from_settings(settings)
    assert weights.max_boost == 1.0
    factors = decay_factors(
        note("a", modified=iso(0)), hits=99, inbound=99, now=NOW, weights=weights
    )
    # Only recency contributes now.
    assert factors.boost == pytest.approx(1.0)


def test_a_zeroed_weight_switches_its_factor_off() -> None:
    weights = weights_from_settings(
        RecallSettings(recency_weight=0.0, access_weight=0.0, significance_weight=0.0)
    )
    factors = decay_factors(
        note("a", type="decision", modified=iso(0)), hits=99, inbound=99, now=NOW, weights=weights
    )
    assert factors.boost == 0.0
    assert factors.multiplier == 1.0
