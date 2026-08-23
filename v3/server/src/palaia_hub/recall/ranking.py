"""Decay-scored ranking on top of SPEC-104's hybrid search.

v2's proven concept, minus the part that aged badly. v2 *moved files* between
hot/warm/cold directories as their score changed; here decay is **logical
only** — a number computed at query time from what the index already knows.
Nothing on disk moves, so a stale score is one query away from being right
again and a wrong weight is a config edit, not a migration.

**Relevance enters as rank, not as score.** The three retrieval modes produce
numbers on incomparable scales: bm25 is negative and logarithmic, cosine
similarity is ``[0, 1]``, RRF sits around ``1/60``. Feeding those into one
formula would make the decay weights mean something different in each mode —
and the mode a query runs in is not the caller's choice (it depends on
whether the embed backlog has drained). Reciprocal rank is the one quantity
all three agree on, so that is what decay multiplies:

    score = 1 / (RANK_K + rank) * (1 + w_r·recency + w_a·access + w_s·significance)

With the default weights the boost caps at 0.65, and :data:`RANK_K` turns
that cap into two concrete bounds: flipping two adjacent results takes a
boost gap of about 0.08 (one tier of the entry taxonomy, or a month of
freshness), and even a maximal boost reaches only about eight ranks. Decay
reshuffles the top of the page with opinions; it is not a second retriever,
and it cannot drag an unrelated-but-fresh note onto a specific query.

**The three factors.**

* **recency** — exponential half-life over the note's ``modified`` (else
  ``created``) frontmatter. A note with neither timestamp scores
  :attr:`RankingWeights.unknown_recency` rather than 0: "undated" is not
  evidence of being stale, and file mtimes are deliberately not consulted
  (they change on checkout, which would make ranking depend on how the vault
  arrived on disk rather than on its content).
* **access** — how often recall has actually served this note, saturating
  logarithmically. Frequently-used memories are what the user keeps coming
  back to; the counter lives in the index (see ``note_access`` in
  :mod:`palaia_hub.index.schema`).
* **significance** — how load-bearing the note is, from two signals that
  need no clock and no counters: its entry type (a ``decision`` outranks a
  ``capture``) and its inbound-link centrality (an entity everything points
  at matters more than a leaf).

Every function here is pure: same inputs, same output, no clock read unless
a ``now`` is handed in. That is what makes the golden-vault ranking battery
a regression test rather than a flake.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from palaia_hub.index import IndexedNote

#: Reciprocal-rank constant for the relevance term. Deliberately *not* the 60
#: SPEC-104's fusion uses (:data:`palaia_hub.index.RRF_K`) — that constant is
#: tuned so mere agreement between two retrievers outweighs either one's rank,
#: which at this layer would mean a 1.6% relevance gap between adjacent hits
#: being overturned by any decay difference at all, exact title matches
#: included. 12 sets the two thresholds where they belong: flipping adjacent
#: ranks needs a boost gap of roughly 0.08 (a whole tier of the entry
#: taxonomy, or a month of freshness), and the reach of a maximal boost is
#: about eight ranks — decay reshuffles the top of the page and cannot touch
#: the rest of it.
RANK_K = 12.0

#: Significance by entry type (format spec §6). A decision or a rule is what
#: the vault exists to keep; an inbox capture is explicitly un-curated
#: material, and ``meta`` is vault self-description that normal recall
#: excludes outright — its weight only matters if a caller asks for it.
DEFAULT_TYPE_SIGNIFICANCE: Mapping[str, float] = MappingProxyType(
    {
        "decision": 1.0,
        "rule": 0.95,
        "process": 0.8,
        "project": 0.7,
        "person": 0.6,
        "note": 0.5,
        "proposal": 0.45,
        "capture": 0.15,
        "meta": 0.1,
    }
)


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """The decay-scoring weights — the tunable half of ranking quality.

    Surfaced in ``config.yaml`` under ``recall:`` (see
    :class:`palaia_hub.config.RecallSettings`), so an operator whose vault
    ranks badly can change the shape of the scoring without a code change.
    """

    recency: float = 0.25
    access: float = 0.15
    significance: float = 0.25

    half_life_days: float = 30.0
    """Days after which the recency term halves."""

    access_saturation: float = 20.0
    """Access count at which the access term reaches 1.0."""

    centrality_saturation: float = 12.0
    """Inbound relation count at which the centrality term reaches 1.0."""

    centrality_weight: float = 0.35
    """How much of significance comes from centrality vs. entry type."""

    unknown_recency: float = 0.5
    """Recency for a note with no ``modified``/``created`` timestamp."""

    type_significance: Mapping[str, float] = field(
        default_factory=lambda: DEFAULT_TYPE_SIGNIFICANCE
    )
    default_type_significance: float = 0.4
    """Significance of an entry type not in :attr:`type_significance` (§6 allows
    unknown types — warn-first, so they must still rank)."""

    @property
    def max_boost(self) -> float:
        """The largest multiplier decay can add to a relevance rank."""
        return self.recency + self.access + self.significance


DEFAULT_WEIGHTS = RankingWeights()


class WeightSettings(Protocol):
    """The config shape :func:`weights_from_settings` reads.

    A structural protocol rather than an import of
    :class:`palaia_hub.config.RecallSettings`: ranking must stay usable (and
    testable) without the hub's configuration machinery in scope.
    """

    @property
    def recency_weight(self) -> float: ...
    @property
    def access_weight(self) -> float: ...
    @property
    def significance_weight(self) -> float: ...
    @property
    def half_life_days(self) -> float: ...
    @property
    def access_saturation(self) -> float: ...
    @property
    def centrality_saturation(self) -> float: ...
    @property
    def centrality_weight(self) -> float: ...
    @property
    def unknown_recency(self) -> float: ...


def weights_from_settings(settings: WeightSettings) -> RankingWeights:
    """Build :class:`RankingWeights` from the hub config's ``recall:`` section."""
    return RankingWeights(
        recency=settings.recency_weight,
        access=settings.access_weight,
        significance=settings.significance_weight,
        half_life_days=settings.half_life_days,
        access_saturation=settings.access_saturation,
        centrality_saturation=settings.centrality_saturation,
        centrality_weight=settings.centrality_weight,
        unknown_recency=settings.unknown_recency,
    )


@dataclass(frozen=True, slots=True)
class DecayFactors:
    """The three normalized factors and the boost they produce, for one note."""

    recency: float
    access: float
    significance: float
    boost: float

    @property
    def multiplier(self) -> float:
        return 1.0 + self.boost


@dataclass(frozen=True, slots=True)
class RankedRef:
    """One ranked candidate: what it is, how it scored, and why."""

    ref: str
    permalink: str
    kind: str
    title: str
    type: str
    snippet: str
    relevance_rank: int
    """0-based position in the retrieval order this candidate came in at."""

    relevance_score: float
    """The retriever's own score, carried through untouched for transparency."""

    factors: DecayFactors
    score: float


def parse_timestamp(raw: str) -> datetime | None:
    """Parse an ISO-8601 frontmatter timestamp, tolerating ``Z`` and bare dates."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def days_between(then: datetime, now: datetime) -> float:
    """Non-negative days from ``then`` to ``now`` (a future date reads as 0)."""
    return max((now - then).total_seconds() / 86400.0, 0.0)


def recency_factor(timestamp: str, *, now: datetime, weights: RankingWeights) -> float:
    """``exp(-ln2 · days / half_life)`` — 1.0 today, 0.5 at one half-life."""
    parsed = parse_timestamp(timestamp)
    if parsed is None:
        return weights.unknown_recency
    if weights.half_life_days <= 0:
        return 1.0
    days = days_between(parsed, now)
    return math.exp(-math.log(2.0) * days / weights.half_life_days)


def access_factor(hits: int, *, weights: RankingWeights) -> float:
    """Logarithmic saturation: the 1st access counts far more than the 20th."""
    if hits <= 0 or weights.access_saturation <= 0:
        return 0.0
    ceiling = math.log1p(weights.access_saturation)
    return min(math.log1p(float(hits)) / ceiling, 1.0)


def significance_factor(
    note_type: str, inbound: int, *, weights: RankingWeights
) -> float:
    """Blend entry-type weight with inbound-link centrality."""
    base = weights.type_significance.get(
        note_type.strip().casefold(), weights.default_type_significance
    )
    if weights.centrality_saturation <= 0:
        centrality = 0.0
    else:
        ceiling = math.log1p(weights.centrality_saturation)
        centrality = min(math.log1p(max(inbound, 0)) / ceiling, 1.0)
    share = min(max(weights.centrality_weight, 0.0), 1.0)
    return (1.0 - share) * base + share * centrality


def decay_factors(
    note: IndexedNote,
    *,
    hits: int,
    inbound: int,
    now: datetime,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> DecayFactors:
    """The decay factors of one note — the pure core of the scoring."""
    recency = recency_factor(note.timestamp, now=now, weights=weights)
    access = access_factor(hits, weights=weights)
    significance = significance_factor(note.type, inbound, weights=weights)
    boost = (
        weights.recency * recency
        + weights.access * access
        + weights.significance * significance
    )
    return DecayFactors(
        recency=recency, access=access, significance=significance, boost=boost
    )


def relevance_of(rank: int) -> float:
    """Reciprocal rank of a 0-based retrieval position (see module docstring)."""
    return 1.0 / (RANK_K + rank + 1.0)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A retrieval hit awaiting decay scoring."""

    ref: str
    permalink: str
    kind: str
    snippet: str
    relevance_score: float


def rank_candidates(
    candidates: Sequence[Candidate],
    notes: Mapping[str, IndexedNote],
    *,
    hits: Mapping[str, int],
    inbound: Mapping[str, int],
    now: datetime,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[RankedRef]:
    """Score and re-order ``candidates``; ties break on ``ref`` alphabetically.

    ``candidates`` must arrive in the retriever's own order — that order *is*
    the relevance term. A candidate whose note is missing from ``notes`` (a
    delete racing a query) is dropped rather than scored against defaults.
    """
    ranked: list[RankedRef] = []
    for rank, candidate in enumerate(candidates):
        note = notes.get(candidate.permalink)
        if note is None:
            continue
        factors = decay_factors(
            note,
            hits=hits.get(candidate.permalink, 0),
            inbound=inbound.get(candidate.permalink, 0),
            now=now,
            weights=weights,
        )
        ranked.append(
            RankedRef(
                ref=candidate.ref,
                permalink=candidate.permalink,
                kind=candidate.kind,
                title=note.title,
                type=note.type,
                snippet=candidate.snippet,
                relevance_rank=rank,
                relevance_score=candidate.relevance_score,
                factors=factors,
                score=relevance_of(rank) * factors.multiplier,
            )
        )
    ranked.sort(key=lambda entry: (-entry.score, entry.ref))
    return [replace(entry, score=round(entry.score, 9)) for entry in ranked]


__all__ = [
    "DEFAULT_TYPE_SIGNIFICANCE",
    "DEFAULT_WEIGHTS",
    "RANK_K",
    "Candidate",
    "DecayFactors",
    "RankedRef",
    "RankingWeights",
    "WeightSettings",
    "access_factor",
    "days_between",
    "decay_factors",
    "parse_timestamp",
    "rank_candidates",
    "recency_factor",
    "relevance_of",
    "significance_factor",
    "weights_from_settings",
]
