"""Relation traversal — the walk behind ``build_context``.

"Continue where we left off" is a graph question, not a search question: the
caller already knows *where* (a ``memory://`` reference, or a query that
finds one), and what they are missing is the neighborhood. Re-searching for
each neighbor would rank them against the query instead of following the
edges the author actually wrote.

Three limits keep the walk honest, and all three are the caller's:

* **depth** — hops from the seeds. Depth 1 is "this note and what it names";
  depth 2 already reaches the notes those name, which on a real vault is
  most of a project's context.
* **timeframe** — a lower bound on a neighbor's own timestamp, so a walk can
  ask for "the part of this graph that is still current". A note with *no*
  timestamp is kept: undated is not evidence of stale (same reasoning as the
  recency factor in :mod:`.ranking`).
* **max_nodes** — a hard stop, because a well-connected vault's depth-3
  neighborhood can be most of the vault.

Cycles are handled by construction: a permalink is enqueued at most once
(``visited``), so ``A → B → A`` visits A once and stops. That is also what
makes each node's ``via``/``parent`` the *shortest* path that reached it —
BFS, so the first arrival wins.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .ranking import parse_timestamp

#: Default hops from the seeds.
DEFAULT_DEPTH = 2

#: Hard ceiling on hops, whatever the caller asks for: beyond this a "walk"
#: is a vault dump, and the token budget would summarize it all to stubs.
MAX_DEPTH = 5

#: Hard ceiling on visited nodes.
DEFAULT_MAX_NODES = 200

_RELATIVE_RE = re.compile(r"^(?P<count>\d+)\s*(?P<unit>[hdwmy])$", re.IGNORECASE)

_UNIT_DAYS = {"h": 1.0 / 24.0, "d": 1.0, "w": 7.0, "m": 30.0, "y": 365.0}


def parse_timeframe(raw: str | None, *, now: datetime) -> datetime | None:
    """Parse a timeframe lower bound: ``"30d"``, ``"2w"``, or an ISO timestamp.

    Returns ``None`` for empty or unparseable input — an unreadable
    timeframe widens the walk rather than silently emptying it, because a
    caller who mistypes a date should get too much context, not none.
    """
    text = (raw or "").strip()
    if not text:
        return None
    match = _RELATIVE_RE.match(text)
    if match is not None:
        days = int(match.group("count")) * _UNIT_DAYS[match.group("unit").lower()]
        return now - timedelta(days=days)
    parsed = parse_timestamp(text)
    return parsed.astimezone(UTC) if parsed is not None else None


class GraphEdge(Protocol):
    """The two things the walk reads off an edge."""

    @property
    def target(self) -> str: ...
    @property
    def label(self) -> str: ...


class TimestampedNote(Protocol):
    """The one thing the timeframe filter reads off a note."""

    @property
    def timestamp(self) -> str: ...


class GraphView(Protocol):
    """What the walk needs from a graph — two methods, no SQL in sight.

    :class:`palaia_hub.index.GraphReader` satisfies this; so does the
    in-memory test double in :mod:`palaia_hub.gateway.fake_vault`. Stating
    the dependency as a protocol is what keeps this module free of the index
    package, and therefore unit-testable against a hand-built graph.
    """

    def neighbors(self, permalink: str) -> Sequence[GraphEdge]: ...

    def note(self, permalink: str) -> TimestampedNote | None: ...


@dataclass(frozen=True, slots=True)
class WalkNode:
    """One node the walk reached, and how it got there."""

    permalink: str
    depth: int
    via: str = ""
    """Edge label that reached this node (``"depends_on →"``, ``"← part_of"``);
    empty for a seed."""

    parent: str = ""
    """Permalink the edge came from; empty for a seed."""

    @property
    def is_seed(self) -> bool:
        return self.depth == 0


@dataclass(frozen=True, slots=True)
class WalkResult:
    """Everything the walk found, plus what it refused to do."""

    nodes: tuple[WalkNode, ...]
    truncated: bool = False
    """True when :data:`DEFAULT_MAX_NODES` (or the caller's) stopped the walk."""

    skipped_by_timeframe: int = 0

    @property
    def permalinks(self) -> tuple[str, ...]:
        return tuple(node.permalink for node in self.nodes)


def clamp_depth(depth: int) -> int:
    """Depth as the walk will actually use it: ``0 <= depth <= MAX_DEPTH``."""
    return max(0, min(int(depth), MAX_DEPTH))


def walk(
    graph: GraphView,
    seeds: Sequence[str],
    *,
    depth: int = DEFAULT_DEPTH,
    since: datetime | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> WalkResult:
    """Breadth-first walk from ``seeds`` over resolved relations, both directions.

    Seeds are always included — the caller named them, so a timeframe filter
    that excluded them would answer a different question than the one asked.
    Deduplication is by permalink across the whole result, so a note reachable
    by three paths appears once, at its shortest depth.
    """
    limit = clamp_depth(depth)
    nodes: list[WalkNode] = []
    visited: set[str] = set()
    queue: deque[WalkNode] = deque()
    truncated = False
    skipped = 0

    for seed in seeds:
        if seed in visited:
            continue
        visited.add(seed)
        node = WalkNode(permalink=seed, depth=0)
        nodes.append(node)
        queue.append(node)

    while queue:
        current = queue.popleft()
        if current.depth >= limit:
            continue
        for edge in graph.neighbors(current.permalink):
            if edge.target in visited:
                continue
            if since is not None and not _within(graph, edge.target, since):
                skipped += 1
                continue
            if len(nodes) >= max_nodes:
                truncated = True
                break
            visited.add(edge.target)
            node = WalkNode(
                permalink=edge.target,
                depth=current.depth + 1,
                via=edge.label,
                parent=current.permalink,
            )
            nodes.append(node)
            queue.append(node)
        if truncated:
            break

    return WalkResult(nodes=tuple(nodes), truncated=truncated, skipped_by_timeframe=skipped)


def _within(graph: GraphView, permalink: str, since: datetime) -> bool:
    note = graph.note(permalink)
    if note is None:  # pragma: no cover - resolved targets exist by construction
        return False
    stamp = parse_timestamp(note.timestamp)
    if stamp is None:
        return True
    return stamp >= since


__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_MAX_NODES",
    "MAX_DEPTH",
    "GraphEdge",
    "GraphView",
    "TimestampedNote",
    "WalkNode",
    "WalkResult",
    "clamp_depth",
    "parse_timeframe",
    "walk",
]
