"""The ranking regression battery (SPEC-106 acceptance criterion #4).

``tests/fixtures/ranking-battery.json`` holds an expected top-3 per query
against the golden ``work`` vault, together with the judgment each row
encodes. This module runs it.

Its value is entirely in *failing*: ranking regressions are silent quality
loss, and the only way to notice that a weight change quietly buried the
right answer is to have written down what the right answer was. A failure
here is therefore not automatically a bug — it is an argument to be had,
with the fixture's ``why`` field as the other side of it. Re-record a row
only after deciding the new order is genuinely better, and update its
``why`` in the same commit.

The conditions the battery runs under are fixed here and documented in the
fixture: embeddings off, access counters off, clock frozen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from recall_helpers import FROZEN_NOW, frozen_clock, open_golden

from palaia_hub.recall import RecallService

pytestmark = pytest.mark.anyio

BATTERY_PATH = Path(__file__).parent.parent / "fixtures" / "ranking-battery.json"


def _battery() -> dict[str, dict[str, Any]]:
    data = json.loads(BATTERY_PATH.read_text(encoding="utf-8"))
    queries: dict[str, dict[str, Any]] = data["queries"]
    return queries


BATTERY = _battery()


def test_every_battery_row_states_its_intent() -> None:
    # A row with no `why` is a row nobody can argue with later.
    for query, row in BATTERY.items():
        assert row.get("why"), f"battery row {query!r} has no `why`"
        assert row.get("top"), f"battery row {query!r} has no expected results"
        assert len(row["top"]) <= 3, f"battery row {query!r} lists more than a top-3"


@pytest.mark.parametrize("query", sorted(BATTERY), ids=lambda q: q.replace(" ", "-"))
async def test_ranking_battery(query: str, tmp_path: Path) -> None:
    engine, index = await open_golden(tmp_path, "work")
    try:
        service = RecallService(
            index, vault=engine.name, track_access=False, clock=frozen_clock()
        )
        result = await service.recall(query=query, limit=3, include_body=False)
        got = [entry.permalink for entry in result.entries]
        expected = list(BATTERY[query]["top"])
        assert got[: len(expected)] == expected, (
            f"ranking drifted for {query!r}\n"
            f"  expected: {expected}\n"
            f"  got:      {got}\n"
            f"  intent:   {BATTERY[query]['why']}\n"
            f"If the new order is genuinely better, re-record this row in "
            f"{BATTERY_PATH.name} and update its `why` in the same commit."
        )
    finally:
        await index.close()
        await engine.close()


async def test_the_battery_is_stable_across_repeated_runs(tmp_path: Path) -> None:
    """Determinism: the same query twice, same order, same scores.

    Not a tautology — the retrieval half runs SQL with no total ordering
    guarantee of its own, and the scoring half reads a clock and a counter
    table. This asserts the composition of all three is deterministic.
    """
    engine, index = await open_golden(tmp_path, "work")
    try:
        service = RecallService(
            index, vault=engine.name, track_access=False, clock=frozen_clock()
        )
        first: dict[str, list[tuple[str, float]]] = {}
        for query in sorted(BATTERY):
            result = await service.recall(query=query, limit=5, include_body=False)
            first[query] = [(entry.permalink, entry.score) for entry in result.entries]
        for _ in range(3):
            for query in sorted(BATTERY):
                result = await service.recall(query=query, limit=5, include_body=False)
                assert [
                    (entry.permalink, entry.score) for entry in result.entries
                ] == first[query], f"{query!r} was not reproducible"
    finally:
        await index.close()
        await engine.close()


async def test_a_reindex_reproduces_the_same_ranking(tmp_path: Path) -> None:
    """Format spec §10: the index is disposable, results come from files alone."""
    engine, index = await open_golden(tmp_path, "work")
    try:
        service = RecallService(
            index, vault=engine.name, track_access=False, clock=frozen_clock()
        )
        before: dict[str, list[str]] = {}
        for query in sorted(BATTERY):
            result = await service.recall(query=query, limit=5, include_body=False)
            before[query] = [entry.permalink for entry in result.entries]
        await index.reindex()
        for query, expected in before.items():
            result = await service.recall(query=query, limit=5, include_body=False)
            assert [entry.permalink for entry in result.entries] == expected, (
                f"{query!r} ranked differently after a reindex"
            )
    finally:
        await index.close()
        await engine.close()


async def test_scores_are_explainable(tmp_path: Path) -> None:
    """Every entry reports the factors that produced its score."""
    engine, index = await open_golden(tmp_path, "work")
    try:
        service = RecallService(
            index, vault=engine.name, track_access=False, clock=frozen_clock()
        )
        result = await service.recall(query="api gateway", limit=5, include_body=False)
        assert result.entries
        for entry in result.entries:
            assert 0.0 <= entry.recency <= 1.0
            assert 0.0 <= entry.access <= 1.0
            assert 0.0 <= entry.significance <= 1.0
            assert entry.score > 0.0
        # Scores are strictly descending — the answer is an ordering, not a set.
        scores = [entry.score for entry in result.entries]
        assert scores == sorted(scores, reverse=True)
    finally:
        await index.close()
        await engine.close()


async def test_the_frozen_clock_is_actually_in_the_past_of_nothing(tmp_path: Path) -> None:
    # Sanity guard on the fixture itself: a battery frozen *before* the golden
    # vault's own timestamps would score every capture as "from the future".
    engine, index = await open_golden(tmp_path, "work")
    try:
        note = index.graph.note("inbox/recall-context-budget")
        assert note is not None
        from palaia_hub.recall.ranking import parse_timestamp

        created = parse_timestamp(note.timestamp)
        assert created is not None and created <= FROZEN_NOW
    finally:
        await index.close()
        await engine.close()
