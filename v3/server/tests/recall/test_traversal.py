"""The relation walk: depth, timeframe, dedup, and never looping on cycles.

Split in two: a hand-built graph for the shapes that are awkward to express
as fixture notes (a tight cycle, a diamond, a long chain), and the golden
vault for the real edge vocabulary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from recall_helpers import FROZEN_NOW

from palaia_hub.index import VaultIndex
from palaia_hub.recall.traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    clamp_depth,
    parse_timeframe,
    walk,
)
from palaia_hub.vault import VaultEngine


@dataclass(frozen=True, slots=True)
class Edge:
    target: str
    type: str

    @property
    def label(self) -> str:
        return f"{self.type} →"


@dataclass(frozen=True, slots=True)
class Node:
    timestamp: str = ""


class Graph:
    """A hand-built :class:`~palaia_hub.recall.traversal.GraphView`."""

    def __init__(
        self,
        edges: dict[str, list[str]],
        stamps: dict[str, str] | None = None,
    ) -> None:
        self._edges = edges
        self._stamps = stamps or {}

    def neighbors(self, permalink: str) -> Sequence[Edge]:
        return [Edge(target, "relates_to") for target in self._edges.get(permalink, [])]

    def note(self, permalink: str) -> Node | None:
        if permalink not in self._edges and permalink not in self._stamps:
            return None
        return Node(timestamp=self._stamps.get(permalink, ""))


def iso(days_ago: float) -> str:
    return (FROZEN_NOW - timedelta(days=days_ago)).isoformat()


# --------------------------------------------------------------------------
# timeframe parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected_days"),
    [("1d", 1), ("30d", 30), ("2w", 14), ("24h", 1), ("3m", 90), ("1y", 365), ("30 d", 30)],
)
def test_relative_timeframes(raw: str, expected_days: float) -> None:
    since = parse_timeframe(raw, now=FROZEN_NOW)
    assert since is not None
    assert (FROZEN_NOW - since).total_seconds() == pytest.approx(expected_days * 86400)


def test_absolute_timeframe_is_normalized_to_utc() -> None:
    since = parse_timeframe("2026-08-01T00:00:00+02:00", now=FROZEN_NOW)
    assert since == datetime(2026, 7, 31, 22, 0, tzinfo=UTC)


@pytest.mark.parametrize("raw", ["", "   ", None, "yesterday", "soon", "17z"])
def test_an_unparseable_timeframe_widens_rather_than_empties(raw: str | None) -> None:
    # A mistyped date must give the caller too much context, never none.
    assert parse_timeframe(raw, now=FROZEN_NOW) is None


# --------------------------------------------------------------------------
# depth
# --------------------------------------------------------------------------

def test_depth_is_clamped_to_the_hard_ceiling() -> None:
    assert clamp_depth(-5) == 0
    assert clamp_depth(0) == 0
    assert clamp_depth(2) == 2
    assert clamp_depth(MAX_DEPTH + 10) == MAX_DEPTH


def test_depth_zero_returns_only_the_seeds() -> None:
    graph = Graph({"a": ["b"], "b": ["c"], "c": []})
    result = walk(graph, ["a"], depth=0)
    assert result.permalinks == ("a",)


@pytest.mark.parametrize(
    ("depth", "expected"),
    [(1, ("a", "b")), (2, ("a", "b", "c")), (3, ("a", "b", "c", "d")), (4, ("a", "b", "c", "d"))],
)
def test_depth_bounds_the_walk_exactly(depth: int, expected: tuple[str, ...]) -> None:
    graph = Graph({"a": ["b"], "b": ["c"], "c": ["d"], "d": []})
    assert walk(graph, ["a"], depth=depth).permalinks == expected


def test_every_node_records_the_hop_that_reached_it() -> None:
    graph = Graph({"a": ["b"], "b": ["c"], "c": []})
    nodes = {node.permalink: node for node in walk(graph, ["a"], depth=2).nodes}
    assert nodes["a"].depth == 0 and nodes["a"].via == "" and nodes["a"].parent == ""
    assert nodes["b"].depth == 1 and nodes["b"].parent == "a"
    assert nodes["b"].via == "relates_to →"
    assert nodes["c"].depth == 2 and nodes["c"].parent == "b"


# --------------------------------------------------------------------------
# cycles and dedup — the acceptance criterion
# --------------------------------------------------------------------------

def test_a_two_node_cycle_terminates() -> None:
    graph = Graph({"a": ["b"], "b": ["a"]})
    result = walk(graph, ["a"], depth=MAX_DEPTH)
    assert result.permalinks == ("a", "b")


def test_a_self_loop_terminates() -> None:
    graph = Graph({"a": ["a"]})
    assert walk(graph, ["a"], depth=MAX_DEPTH).permalinks == ("a",)


def test_a_long_cycle_terminates() -> None:
    graph = Graph({"a": ["b"], "b": ["c"], "c": ["d"], "d": ["a"]})
    result = walk(graph, ["a"], depth=MAX_DEPTH)
    assert sorted(result.permalinks) == ["a", "b", "c", "d"]


def test_a_fully_connected_graph_terminates_and_deduplicates() -> None:
    keys = [f"n{n}" for n in range(12)]
    graph = Graph({key: [other for other in keys if other != key] for key in keys})
    result = walk(graph, ["n0"], depth=MAX_DEPTH)
    assert sorted(result.permalinks) == sorted(keys)
    assert len(set(result.permalinks)) == len(result.permalinks)


def test_a_diamond_reports_each_node_once_at_its_shortest_depth() -> None:
    graph = Graph({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []})
    nodes = {node.permalink: node for node in walk(graph, ["a"], depth=3).nodes}
    assert set(nodes) == {"a", "b", "c", "d"}
    assert nodes["d"].depth == 2


def test_repeated_seeds_are_deduplicated() -> None:
    graph = Graph({"a": [], "b": []})
    assert walk(graph, ["a", "a", "b", "a"], depth=1).permalinks == ("a", "b")


def test_max_nodes_stops_the_walk_and_says_so() -> None:
    keys = [f"n{n}" for n in range(50)]
    graph = Graph({key: keys for key in keys})
    result = walk(graph, ["n0"], depth=MAX_DEPTH, max_nodes=5)
    assert result.truncated
    assert len(result.nodes) <= 5


# --------------------------------------------------------------------------
# timeframe filtering
# --------------------------------------------------------------------------

def test_the_timeframe_excludes_stale_neighbors_and_counts_them() -> None:
    graph = Graph(
        {"a": ["fresh", "stale"], "fresh": [], "stale": []},
        {"a": iso(0), "fresh": iso(5), "stale": iso(400)},
    )
    result = walk(graph, ["a"], depth=1, since=parse_timeframe("30d", now=FROZEN_NOW))
    assert result.permalinks == ("a", "fresh")
    assert result.skipped_by_timeframe == 1


def test_the_timeframe_never_excludes_a_seed() -> None:
    # The caller named it; filtering it out would answer a different question.
    graph = Graph({"ancient": []}, {"ancient": iso(9999)})
    result = walk(graph, ["ancient"], depth=1, since=parse_timeframe("1d", now=FROZEN_NOW))
    assert result.permalinks == ("ancient",)


def test_an_undated_neighbor_survives_the_timeframe() -> None:
    graph = Graph({"a": ["undated"], "undated": []}, {"a": iso(0)})
    result = walk(graph, ["a"], depth=1, since=parse_timeframe("1d", now=FROZEN_NOW))
    assert result.permalinks == ("a", "undated")


def test_the_timeframe_blocks_traversal_through_an_excluded_node() -> None:
    graph = Graph(
        {"a": ["stale"], "stale": ["beyond"], "beyond": []},
        {"a": iso(0), "stale": iso(400), "beyond": iso(0)},
    )
    result = walk(graph, ["a"], depth=3, since=parse_timeframe("30d", now=FROZEN_NOW))
    assert result.permalinks == ("a",)


# --------------------------------------------------------------------------
# Against the golden vault's real edges
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_the_walk_follows_both_directions_on_the_golden_vault(
    golden_work: tuple[VaultEngine, VaultIndex],
) -> None:
    _, index = golden_work
    # Recall Engine declares `depends_on [[Vault Engine]]`; Files Are Truth
    # declares `decided_in [[Vault Engine]]`. From Recall Engine, depth 2 must
    # therefore reach Files Are Truth — through an inbound edge on Vault
    # Engine, which a forward-only walk would never see.
    result = walk(index.graph, ["projects/recall-engine"], depth=2)
    assert "projects/vault-engine" in result.permalinks
    assert "decisions/files-are-truth" in result.permalinks
    nodes = {node.permalink: node for node in result.nodes}
    assert nodes["projects/vault-engine"].via == "depends_on →"
    assert nodes["decisions/files-are-truth"].via == "← decided_in"


@pytest.mark.anyio
async def test_an_unresolved_forward_reference_is_not_walked_to(
    golden_work: tuple[VaultEngine, VaultIndex],
) -> None:
    _, index = golden_work
    # Legacy Migration declares `blocked_by [[Q3 Roadmap]]`, and no such note
    # exists (format spec §5.2). There is nothing to walk to, and that must
    # not be an error either.
    result = walk(index.graph, ["projects/legacy-migration"], depth=DEFAULT_DEPTH)
    assert "projects/importer-suite" in result.permalinks
    assert not any("roadmap" in permalink for permalink in result.permalinks)


@pytest.mark.anyio
async def test_the_golden_vaults_embed_cycle_does_not_loop_the_walk(
    golden_work: tuple[VaultEngine, VaultIndex],
) -> None:
    _, index = golden_work
    result = walk(index.graph, ["embeds/cycle-a"], depth=MAX_DEPTH)
    assert len(set(result.permalinks)) == len(result.permalinks)
