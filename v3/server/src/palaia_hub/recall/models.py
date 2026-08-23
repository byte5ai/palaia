"""Value types of the recall API — and the tool payloads they become.

Pydantic rather than dataclasses, unlike the vault and index packages: these
objects *are* the ``recall``/``build_context`` tools' structured output
(:mod:`palaia_hub.gateway.memory_tools` returns them verbatim as
``structured_content``), so defining them once here is what keeps the tool
schema and the recall layer from drifting apart. Field names mirror
``docs/vault-format.md`` on purpose.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecallObservation(BaseModel):
    """One observation served to the calling model (variants already resolved)."""

    ref: str = ""
    """The observation's synthetic permalink (format spec §9.2)."""

    category: str
    scope: str | None = None
    text: str
    context: str | None = None
    block_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class RecallEntry(BaseModel):
    """One recalled thing, with its score decomposed.

    The four score fields are deliberately exposed: a ranking that cannot be
    explained cannot be tuned, and ``recency``/``access``/``significance``
    are exactly the knobs ``config.yaml``'s ``recall:`` section weights.
    """

    ref: str
    permalink: str
    title: str
    type: str = "note"
    kind: str = "note"
    snippet: str = ""
    score: float = 0.0
    relevance_rank: int = 0
    recency: float = 0.0
    access: float = 0.0
    significance: float = 0.0
    body: str = ""
    """The note's body with value references resolved and variants applied."""

    observations: list[RecallObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    """Resolution warnings (``embed-missing``, ``embed-cycle``) for this entry."""


class RecallResult(BaseModel):
    """What one ``recall`` call answers."""

    query: str = ""
    ref: str = ""
    model: str = ""
    """The model identity variant resolution was performed for, as resolved."""

    entries: list[RecallEntry] = Field(default_factory=list)
    matched: int = 0
    """Candidates considered before the limit was applied."""

    degraded: bool = False
    degraded_reason: str = ""
    warnings: list[str] = Field(default_factory=list)


class ContextNode(BaseModel):
    """One note in an assembled context package."""

    ref: str
    permalink: str
    title: str
    type: str = "note"
    depth: int = 0
    via: str = ""
    parent: str = ""
    tier: str = "full"
    """``full`` | ``summary`` | ``stub`` — how much of the note is included."""

    tokens: int = 0
    text: str = ""
    observations: list[RecallObservation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContextResult(BaseModel):
    """A deduplicated, budgeted context package."""

    seeds: list[str] = Field(default_factory=list)
    query: str = ""
    model: str = ""
    depth: int = 0
    timeframe: str = ""
    max_tokens: int = 0
    """The *effective* budget — the requested one, raised to the floor if needed."""

    requested_max_tokens: int = 0
    estimated_tokens: int = 0
    nodes: list[ContextNode] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    """Permalinks the walk found but the budget could not fit at any tier."""

    walk_truncated: bool = False
    skipped_by_timeframe: int = 0
    degraded: bool = False
    """True when anything was summarized, stubbed or dropped for the budget."""

    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "ContextNode",
    "ContextResult",
    "RecallEntry",
    "RecallObservation",
    "RecallResult",
]
