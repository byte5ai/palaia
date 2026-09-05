"""Graph- and identity-shaped reads over the index — recall's data access.

SPEC-104 gave the index its *search* read side (:mod:`.search`). SPEC-106
needs a different shape of read from the same tables: resolve a
``memory://`` reference through the format spec's ordered lookup, walk
relations in both directions, fetch a note's observations, and read/record
the access counters that feed decay scoring.

All of that is SQL, so it lives here in the index package next to the schema
it queries rather than in :mod:`palaia_hub.recall`, which stays free of SQL
and works against the value types below. Search is *not* reimplemented here:
recall calls :meth:`~.service.VaultIndex.search` for retrieval and uses this
module only for what search does not answer.

:meth:`GraphReader.record_access` is the one index mutation outside
:class:`~.writer.IndexWriter`. It touches only ``note_access`` (see that
table's comment in :mod:`.schema`), never a row derived from a file.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from .db import IndexDatabase

#: Which way a relation was traversed to reach a node.
Direction = Literal["out", "in"]


@dataclass(frozen=True, slots=True)
class IndexedNote:
    """One note as the recall layer sees it: identity, text, timestamps."""

    permalink: str
    path: str
    title: str
    type: str
    folder: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]
    created: str
    modified: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)

    @property
    def timestamp(self) -> str:
        """The note's own best-known age signal: ``modified`` else ``created``."""
        return self.modified or self.created


@dataclass(frozen=True, slots=True)
class IndexedObservation:
    """One observation row, addressable by its synthetic permalink (§9.2)."""

    ref: str
    note_permalink: str
    category: str
    scope: str | None
    text: str
    tags: tuple[str, ...]
    context: str | None
    block_id: str | None
    line: int


@dataclass(frozen=True, slots=True)
class Edge:
    """One traversable relation, oriented from the node it was found on."""

    source: str
    """Permalink of the note the walk was standing on."""

    target: str
    """Permalink of the note this edge leads to (always resolved)."""

    type: str
    direction: Direction
    implicit: bool
    context: str | None
    ref: str
    """The relation's own synthetic permalink (§9.2)."""

    @property
    def label(self) -> str:
        """Human-readable edge label, arrow showing which way it points."""
        return f"{self.type} →" if self.direction == "out" else f"← {self.type}"


@dataclass(frozen=True, slots=True)
class AccessStat:
    """How often recall has served a permalink, and when it last did."""

    hits: int = 0
    last_access: str = ""


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Compile a ``memory://`` glob (§3.2): ``*`` in a segment, ``**`` across.

    ``**`` is matched before ``*`` so ``projects/**`` crosses ``/`` while
    ``projects/api-*`` stays inside one segment. ``?`` (one character, no
    slash) is accepted as the obvious companion the spec does not enumerate.
    Everything else in the pattern is escaped, so a glob can never smuggle in
    regex syntax — a permalink containing ``.`` or ``+`` is a literal.
    """
    out: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if pattern.startswith("**", index):
                out.append(".*")
                index += 2
                continue
            out.append("[^/]*")
            index += 1
            continue
        if char == "?":
            out.append("[^/]")
            index += 1
            continue
        out.append(re.escape(char))
        index += 1
    out.append("$")
    return re.compile("".join(out))


def _json_list(raw: object) -> tuple[str, ...]:
    try:
        value = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:  # pragma: no cover - writer always writes JSON
        return ()
    if not isinstance(value, list):  # pragma: no cover - defensive
        return ()
    return tuple(str(item) for item in value)


def _row_to_note(row: sqlite3.Row) -> IndexedNote:
    try:
        frontmatter = json.loads(str(row["frontmatter"] or "{}"))
    except json.JSONDecodeError:  # pragma: no cover - writer always writes JSON
        frontmatter = {}
    return IndexedNote(
        permalink=str(row["permalink"]),
        path=str(row["path"]),
        title=str(row["title"]),
        type=str(row["type"]),
        folder=str(row["folder"]),
        tags=_json_list(row["tags"]),
        aliases=_json_list(row["aliases"]),
        created=str(row["created"] or ""),
        modified=str(row["modified"] or ""),
        body=str(row["body"] or ""),
        frontmatter=frontmatter if isinstance(frontmatter, dict) else {},
    )


_NOTE_COLUMNS = (
    "permalink, path, title, type, folder, tags, aliases, created, modified, body, frontmatter"
)


class GraphReader:
    """Identity, graph and access reads over one vault's index."""

    def __init__(self, db: IndexDatabase) -> None:
        self._db = db

    # ------------------------------------------------------------- identity

    def note(self, permalink: str) -> IndexedNote | None:
        """The note with exactly this permalink, or ``None``."""
        with self._db.lock:
            row = self._db.conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes WHERE permalink = ? ORDER BY path LIMIT 1",
                (permalink,),
            ).fetchone()
        return None if row is None else _row_to_note(row)

    def notes(self, permalinks: Sequence[str]) -> dict[str, IndexedNote]:
        """Fetch several notes at once, keyed by permalink."""
        if not permalinks:
            return {}
        unique = sorted(set(permalinks))
        placeholders = ",".join("?" for _ in unique)
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT {_NOTE_COLUMNS} FROM notes WHERE permalink IN ({placeholders}) "
                "ORDER BY permalink, path",
                unique,
            ).fetchall()
        found: dict[str, IndexedNote] = {}
        for row in rows:
            note = _row_to_note(row)
            found.setdefault(note.permalink, note)
        return found

    # The four resolution tiers of format spec §3.2, each returning *every*
    # match so the caller can report ambiguity with candidates listed rather
    # than silently picking one.

    def by_permalink(self, candidate: str) -> list[str]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT DISTINCT permalink FROM notes WHERE permalink = ? ORDER BY permalink",
                (candidate,),
            ).fetchall()
        return [str(row["permalink"]) for row in rows]

    def by_alias(self, candidate: str) -> list[str]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT DISTINCT n.permalink FROM notes n, json_each(n.aliases) a "
                "WHERE lower(a.value) = ? ORDER BY n.permalink",
                (candidate.lower(),),
            ).fetchall()
        return [str(row["permalink"]) for row in rows]

    def by_title(self, candidate: str) -> list[str]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT DISTINCT permalink FROM notes WHERE lower(title) = ? ORDER BY permalink",
                (candidate.strip().lower(),),
            ).fetchall()
        return [str(row["permalink"]) for row in rows]

    def by_path_suffix(self, candidate: str) -> list[str]:
        """Notes whose path is, or ends with a full segment matching, ``candidate``."""
        needle = candidate.strip("/")
        if not needle:
            return []
        if not needle.endswith(".md"):
            needle += ".md"
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT DISTINCT permalink FROM notes WHERE path = ? OR path LIKE ? "
                "ORDER BY permalink",
                (needle, f"%/{needle}"),
            ).fetchall()
        return [str(row["permalink"]) for row in rows]

    def matching_glob(self, pattern: str) -> list[str]:
        """Permalinks matching a ``memory://`` glob, sorted (§3.2)."""
        regex = _glob_to_regex(pattern)
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT DISTINCT permalink FROM notes ORDER BY permalink"
            ).fetchall()
        return [
            str(row["permalink"]) for row in rows if regex.match(str(row["permalink"])) is not None
        ]

    # ---------------------------------------------------------- sub-note refs

    def observation_by_ref(self, ref: str) -> IndexedObservation | None:
        """An observation addressed by its synthetic permalink (§9.2)."""
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT o.permalink AS ref, n.permalink AS note_permalink, o.category, o.scope, "
                "o.text, o.tags, o.context, o.block_id, o.line "
                "FROM observations o JOIN notes n ON n.id = o.note_id "
                "WHERE o.permalink = ? ORDER BY o.id LIMIT 1",
                (ref,),
            ).fetchone()
        return None if row is None else _row_to_observation(row)

    def relation_by_ref(self, ref: str) -> Edge | None:
        """A relation addressed by its synthetic permalink (§9.2)."""
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT r.permalink AS ref, n.permalink AS source, r.type, r.target_raw, "
                "r.target_permalink, r.implicit, r.context "
                "FROM relations r JOIN notes n ON n.id = r.note_id "
                "WHERE r.permalink = ? ORDER BY r.id LIMIT 1",
                (ref,),
            ).fetchone()
        if row is None:
            return None
        return Edge(
            source=str(row["source"]),
            target=str(row["target_permalink"] or ""),
            type=str(row["type"]),
            direction="out",
            implicit=bool(row["implicit"]),
            context=None if row["context"] is None else str(row["context"]),
            ref=str(row["ref"]),
        )

    def observations(self, permalink: str) -> list[IndexedObservation]:
        """A note's observations in file order (variant groups intact)."""
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT o.permalink AS ref, n.permalink AS note_permalink, o.category, o.scope, "
                "o.text, o.tags, o.context, o.block_id, o.line "
                "FROM observations o JOIN notes n ON n.id = o.note_id "
                "WHERE n.permalink = ? ORDER BY o.line, o.id",
                (permalink,),
            ).fetchall()
        return [_row_to_observation(row) for row in rows]

    # ------------------------------------------------------------- traversal

    def neighbors(self, permalink: str) -> list[Edge]:
        """Every resolved relation touching ``permalink``, both directions.

        Outbound edges are this note's own relation lines; inbound edges are
        other notes' relations pointing at it (backlinks). Traversal needs
        both: "what does this decision depend on" and "what depends on this
        decision" are the same question asked from two ends, and a context
        package that only followed one of them would miss half the graph.

        Unresolved forward references (``target_permalink IS NULL``, §5.2)
        are skipped — there is no node to walk to yet.
        """
        with self._db.lock:
            out_rows = self._db.conn.execute(
                "SELECT r.permalink AS ref, r.type, r.target_permalink AS target, "
                "r.implicit, r.context "
                "FROM relations r JOIN notes n ON n.id = r.note_id "
                "WHERE n.permalink = ? AND r.target_permalink IS NOT NULL "
                "ORDER BY r.line, r.id",
                (permalink,),
            ).fetchall()
            in_rows = self._db.conn.execute(
                "SELECT r.permalink AS ref, r.type, n.permalink AS target, "
                "r.implicit, r.context "
                "FROM relations r JOIN notes n ON n.id = r.note_id "
                "WHERE r.target_permalink = ? ORDER BY n.permalink, r.line, r.id",
                (permalink,),
            ).fetchall()
        passes: tuple[tuple[Direction, list[sqlite3.Row]], ...] = (
            ("out", out_rows),
            ("in", in_rows),
        )
        edges = [
            Edge(
                source=permalink,
                target=str(row["target"]),
                type=str(row["type"]),
                direction=direction,
                implicit=bool(row["implicit"]),
                context=None if row["context"] is None else str(row["context"]),
                ref=str(row["ref"]),
            )
            for direction, rows in passes
            for row in rows
        ]
        # Self-relations produce an out and an in edge to the same node; the
        # walk's visited set handles that, but dropping the duplicate here
        # keeps edge lists (and therefore `via` labels) stable.
        seen: set[tuple[str, str, str]] = set()
        unique: list[Edge] = []
        for edge in edges:
            key = (edge.target, edge.type, edge.direction)
            if key in seen or edge.target == "":
                continue
            seen.add(key)
            unique.append(edge)
        return unique

    def inbound_count(self, permalink: str) -> int:
        """How many relations point at ``permalink`` — its graph centrality."""
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT COUNT(*) AS n FROM relations WHERE target_permalink = ?",
                (permalink,),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def inbound_counts(self, permalinks: Sequence[str]) -> dict[str, int]:
        """Inbound relation counts for several permalinks at once."""
        if not permalinks:
            return {}
        unique = sorted(set(permalinks))
        placeholders = ",".join("?" for _ in unique)
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT target_permalink AS p, COUNT(*) AS n FROM relations "
                f"WHERE target_permalink IN ({placeholders}) GROUP BY target_permalink",
                unique,
            ).fetchall()
        counts = {permalink: 0 for permalink in unique}
        for row in rows:
            counts[str(row["p"])] = int(row["n"])
        return counts

    # ---------------------------------------------------------------- access

    def access(self, permalinks: Sequence[str]) -> dict[str, AccessStat]:
        """Access counters for ``permalinks``; unseen permalinks read as zero."""
        stats = {permalink: AccessStat() for permalink in permalinks}
        if not permalinks:
            return stats
        unique = sorted(set(permalinks))
        placeholders = ",".join("?" for _ in unique)
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT permalink, hits, last_access FROM note_access "
                f"WHERE permalink IN ({placeholders})",
                unique,
            ).fetchall()
        for row in rows:
            stats[str(row["permalink"])] = AccessStat(
                hits=int(row["hits"]), last_access=str(row["last_access"] or "")
            )
        return stats

    def record_access(self, permalinks: Iterable[str], *, at: str) -> None:
        """Increment the access counter of every permalink in ``permalinks``.

        Called *after* a recall has been ranked, never before: a call must
        not influence its own ranking, or the same query would return a
        different order on its second run (SPEC-106: "deterministic given
        equal inputs").
        """
        values = [(permalink, at) for permalink in dict.fromkeys(permalinks) if permalink]
        if not values:
            return
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT INTO note_access(permalink, hits, last_access) VALUES (?, 1, ?) "
                "ON CONFLICT(permalink) DO UPDATE SET hits = hits + 1, last_access = excluded"
                ".last_access",
                values,
            )
            self._db.commit()


def _row_to_observation(row: sqlite3.Row) -> IndexedObservation:
    return IndexedObservation(
        ref=str(row["ref"]),
        note_permalink=str(row["note_permalink"]),
        category=str(row["category"]),
        scope=None if row["scope"] is None else str(row["scope"]),
        text=str(row["text"]),
        tags=_json_list(row["tags"]),
        context=None if row["context"] is None else str(row["context"]),
        block_id=None if row["block_id"] is None else str(row["block_id"]),
        line=int(row["line"]),
    )


__all__ = [
    "AccessStat",
    "Direction",
    "Edge",
    "GraphReader",
    "IndexedNote",
    "IndexedObservation",
]
