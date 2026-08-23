"""Value types of the index and search API, plus the synthetic-permalink rules.

Synthetic permalinks (format spec §9.2) are *derived, never stored in files*:
``<permalink>/obs/<category-slug>/<h8>`` for an observation and
``<permalink>/rel/<type-slug>/<target>`` for a relation. They are what makes
a search hit addressable below note granularity — a result can point at the
one observation line that matched instead of at a 300-line note.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from palaia_hub.vault import permalink as pl

#: The three search modes of the hybrid API (SPEC-104 deliverable #3).
SearchMode = Literal["fts", "vector", "hybrid"]

#: The addressable granularities a hit can have.
HitKind = Literal["note", "observation", "relation"]

#: Embedding lifecycle of one chunk.
ChunkState = Literal["pending", "ready", "failed"]


def text_hash8(text: str) -> str:
    """First 8 hex of sha256 over ``text`` — the ``h8`` of §9.2."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def fingerprint(text: str) -> str:
    """Content fingerprint of a chunk (16 hex of sha256).

    Longer than ``h8`` on purpose: this one gates whether an existing vector
    may be reused, so an accidental collision would serve a wrong embedding.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def observation_permalink(note_permalink: str, category: str, text: str) -> str:
    """``<permalink>/obs/<category-slug>/<h8>`` (§9.2)."""
    return f"{note_permalink}/obs/{pl.slugify(category) or 'obs'}/{text_hash8(text)}"


def relation_permalink(
    note_permalink: str, relation_type: str, target_permalink: str | None, target_raw: str
) -> str:
    """``<permalink>/rel/<type-slug>/<target-permalink>`` (§9.2).

    An unresolved forward reference has no target permalink yet, so the
    slugified raw target stands in — the synthetic permalink stays stable
    when the target later appears *if* the target's permalink slug matches,
    and changes otherwise. Either way it is derived, never persisted in a
    file, so nothing on disk depends on it.
    """
    target = target_permalink or pl.slugify(target_raw) or "unresolved"
    return f"{note_permalink}/rel/{pl.slugify(relation_type) or 'rel'}/{target}"


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Metadata filters applied to any search mode.

    ``scope`` is a folder prefix (``"projects"`` matches ``projects`` and
    ``projects/api``), ``meta`` filters on flattened frontmatter keys — the
    unknown-keys-are-searchable-metadata promise of §2.1.
    """

    scope: str | None = None
    types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    since: str | None = None
    until: str | None = None
    meta: tuple[tuple[str, str], ...] = ()
    kinds: tuple[HitKind, ...] = ()
    exclude_types: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (
            self.scope
            or self.types
            or self.tags
            or self.since
            or self.until
            or self.meta
            or self.kinds
            or self.exclude_types
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One search result, addressable at its own granularity."""

    ref: str
    """The synthetic (or note) permalink this hit points at (§9.2)."""

    permalink: str
    """The containing note's permalink."""

    kind: HitKind
    title: str
    snippet: str
    score: float
    path: str = ""
    type: str = "note"
    tags: tuple[str, ...] = ()
    modified: str = ""
    fts_rank: int | None = None
    vector_rank: int | None = None


@dataclass(frozen=True, slots=True)
class SearchResults:
    """A result page plus how it was produced.

    ``degraded`` is the honest signal SPEC-104's last acceptance criterion
    asks for: a hybrid query answered from FTS alone because vectors are
    still pending (or unavailable) says so instead of pretending.
    """

    hits: tuple[SearchHit, ...]
    mode: SearchMode
    effective_mode: SearchMode
    degraded: bool = False
    degraded_reason: str = ""

    def __len__(self) -> int:
        return len(self.hits)

    def __iter__(self) -> Iterator[SearchHit]:
        return iter(self.hits)


@dataclass(frozen=True, slots=True)
class EmbedStatus:
    """Embedding backlog — SPEC-104's "embed backlog visible via status API"."""

    enabled: bool
    available: bool
    model: str
    dim: int
    total: int = 0
    ready: int = 0
    pending: int = 0
    failed: int = 0
    reason: str = ""

    @property
    def usable(self) -> bool:
        """True when a vector query can return anything at all."""
        return self.enabled and self.available and self.ready > 0


@dataclass(frozen=True, slots=True)
class IndexStatus:
    """Everything the dashboard/CLI needs to describe one vault's index."""

    vault: str
    path: str
    schema_version: int
    notes: int
    observations: int
    relations: int
    unresolved_relations: int
    embeds: EmbedStatus
    counts_by_type: dict[str, int] = field(default_factory=dict)


__all__ = [
    "ChunkState",
    "EmbedStatus",
    "HitKind",
    "IndexStatus",
    "SearchFilters",
    "SearchHit",
    "SearchMode",
    "SearchResults",
    "fingerprint",
    "observation_permalink",
    "relation_permalink",
    "text_hash8",
]
