"""The narrow contract the memory tool family is written against.

SPEC-102 (vault engine) is developed in parallel on its own branch and is
**not merged yet** — this module MUST NOT import ``palaia_hub.vault`` or
anything else from that lane. Instead it defines the eight-operation surface
the gateway's tools need (search/read/write/edit/move/delete/list/
recent_activity) as a :class:`typing.Protocol`, plus the small result types
those operations return. Anything implementing this protocol — the
in-memory :class:`~palaia_hub.gateway.fake_vault.FakeVaultService` used by
this SPEC's tests today, and a real vault-engine adapter once SPEC-102 lands
and SPEC-113 wires it in — can back the tools built in
:mod:`palaia_hub.gateway.memory_tools`.

Field names below intentionally mirror ``v3/docs/vault-format.md`` (permalink,
title, type, tags, folder) so a future real adapter is a thin pass-through,
not a translation layer.

SPEC-107 adds ``capture``/``inbox_status`` (the inbox/capture contract,
format spec §7) to this same protocol, kept as their own
:data:`INBOX_TOOL_ACTIONS` tuple rather than folded into
:data:`MEMORY_TOOL_ACTIONS` — see that constant's comment.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from palaia_hub.recall.models import ContextResult, RecallResult

# The eight memory tool actions, in the order SPEC-105's deliverables list
# them. This is the single source of truth for "what actions exist" — used
# to build each vault's tool server (memory_tools.py) and to validate
# config-driven renames (gateway/config.py) against a closed set.
MEMORY_TOOL_ACTIONS: tuple[str, ...] = (
    "search",
    "read",
    "write",
    "edit",
    "move",
    "delete",
    "list",
    "recent_activity",
)

# SPEC-107's two inbox/capture actions. Kept as a separate tuple rather than
# folded into MEMORY_TOOL_ACTIONS: that tuple is also used by
# gateway/config.py to validate `tool_renames` keys against the eight
# original actions specifically, and existing config/tests referencing "the
# eight actions" should not silently start meaning ten. Both tuples are
# exposed together in the same tool family server (memory_tools.py).
INBOX_TOOL_ACTIONS: tuple[str, ...] = ("capture", "inbox_status")

# SPEC-106's two recall actions, a separate tuple for the same reason as
# INBOX_TOOL_ACTIONS above. Both are read-only (see
# palaia_hub.auth.scopes.READ_ACTIONS) and both live in the same tool family
# server as the rest.
RECALL_TOOL_ACTIONS: tuple[str, ...] = ("recall", "build_context")

# SPEC-208's three MCP-Apps actions, same separate-tuple reasoning as above.
# ``review_queue`` and ``recall_pick`` are read-only (added to
# palaia_hub.auth.scopes.READ_ACTIONS); ``review_decide`` mutates a
# proposal's frontmatter status and is deliberately left off that allow-list
# so it falls through to the fail-closed "write" default.
APP_TOOL_ACTIONS: tuple[str, ...] = ("review_queue", "review_decide", "recall_pick")


class NoteSummary(BaseModel):
    """Enough to list, browse, or pick a note without fetching its body."""

    permalink: str
    title: str
    type: str = "note"
    tags: list[str] = Field(default_factory=list)
    folder: str = ""
    modified: str = ""
    # Format spec §2.1 schema keys, relevant beyond captures (any note may
    # carry a lifecycle `status`) but populated in practice by SPEC-107's
    # inbox contract: `status: uncurated` and a derived `capture_id`.
    status: str = ""
    capture_id: str = ""

    @property
    def timestamp(self) -> str:
        """The note's age signal, matching :class:`palaia_hub.index.IndexedNote`.

        Lets a summary stand in wherever the recall layer's traversal wants
        something timestamped (``palaia_hub.recall.traversal.GraphView``).
        """
        return self.modified


class NoteRecord(NoteSummary):
    """A full note: everything in :class:`NoteSummary` plus its body.

    ``body`` is always the note **as written** — the raw markdown, embeds
    still embeds. ``resolved_body`` is that same body with value references
    resolved live (format spec §5.3, SPEC-106) and per-model variants
    applied, and is populated only when it actually differs. Both are
    reported because they answer different questions: an agent about to
    *edit* the note needs the source, an agent *reading* it needs the current
    values. The tool's human-readable text uses the resolved form when there
    is one.
    """

    body: str = ""
    created: str = ""
    resolved_body: str = ""
    resolution_warnings: list[str] = Field(default_factory=list)


class CaptureResult(BaseModel):
    """What a ``capture`` call reports: where it landed, or that it didn't.

    ``duplicate=True`` means an exact-duplicate capture already exists in
    ``inbox/`` (format spec §7's dedup guard) — the call is acknowledged but
    no second file is created; ``permalink``/``capture_id`` then identify the
    existing entry.
    """

    permalink: str
    title: str
    capture_id: str
    status: str = "uncurated"
    duplicate: bool = False


class SimilarNoteHit(BaseModel):
    """An existing note that closely resembles a just-written one (issue #187).

    ``similarity`` is a true cosine similarity (0..1, higher = closer in
    meaning) — never a rank or a BM25 score, which only order one query's
    hits and cannot be held against a fixed threshold (issue #481).
    """

    permalink: str
    title: str
    similarity: float


class InboxStatusResult(BaseModel):
    """Inbox health: how many uncurated captures, the oldest, the newest."""

    count: int
    oldest_capture_id: str | None = None
    oldest_age_seconds: float | None = None
    last_capture_id: str | None = None
    last_captured_at: str | None = None


#: The retrieval channels a hit can come from, in the agent-facing wording:
#: ``text`` is the full-text/BM25 channel, ``meaning`` the vector/semantic one.
SearchChannel = Literal["text", "meaning"]

#: The search modes a caller can ask for. Mirrors
#: :data:`palaia_hub.index.models.SearchMode`, restated here rather than
#: imported — this module deliberately depends on nothing from that lane
#: (see the module docstring).
RequestedSearchMode = Literal["fts", "vector", "hybrid"]

#: How a result set was actually produced: the requested modes plus ``scan``,
#: the index-less substring fallback an adapter uses when no index is open.
EffectiveSearchMode = Literal["fts", "vector", "hybrid", "scan"]


def matched_channels(
    *,
    fts_rank: int | None,
    vector_rank: int | None,
    effective_mode: str,
) -> list[SearchChannel]:
    """Which retrieval channel(s) produced a hit, in agent-facing wording.

    The index populates ``fts_rank``/``vector_rank`` only on the fused
    hybrid path — a single-channel result set (an FTS-only query, or a
    hybrid one degraded to FTS) leaves both unset, and every hit in it then
    belongs to that one channel by construction. Deriving the fallback from
    ``effective_mode`` here keeps that from surfacing as "matched by
    nothing".
    """
    channels: list[SearchChannel] = []
    if fts_rank is not None:
        channels.append("text")
    if vector_rank is not None:
        channels.append("meaning")
    if channels:
        return channels
    if effective_mode == "vector":
        return ["meaning"]
    if effective_mode in ("fts", "scan"):
        return ["text"]
    return []


class SearchHit(BaseModel):
    """One search result: a note plus why it matched.

    The provenance fields (SPEC-104's per-hit ranks, passed through here)
    let an agent weigh a hit by *how* it was found: ``matched`` names the
    channel(s) in plain words, and ``fts_rank``/``vector_rank`` are its
    rank within each channel — **1-based**, so rank 1 is that channel's
    best answer (the index counts from zero internally; the adapter shifts
    it once, here at the agent-facing boundary, rather than publishing an
    off-by-one that every reader has to know about). A rank is unset when
    the hit did not come from that channel, or when the result set used a
    single channel throughout (see :func:`matched_channels`).
    """

    permalink: str
    title: str
    snippet: str = ""
    score: float = 0.0
    matched: list[SearchChannel] = Field(default_factory=list)
    fts_rank: int | None = None
    vector_rank: int | None = None


class SearchResponse(BaseModel):
    """A search result page plus how it was produced.

    The honesty half of SPEC-104 at the tool boundary: ``mode`` is what was
    asked for, ``effective_mode`` what actually ran, and ``degraded``/
    ``degraded_reason`` say so when the two differ — a hybrid query answered
    from full-text alone because vectors are still pending reports that
    instead of pretending it was semantic.
    """

    hits: list[SearchHit] = Field(default_factory=list)
    mode: RequestedSearchMode = "hybrid"
    effective_mode: EffectiveSearchMode = "hybrid"
    degraded: bool = False
    degraded_reason: str = ""


class ProposalSummary(BaseModel):
    """One curator maintenance proposal (format spec §8), for the review queue.

    ``body`` is the proposal's full markdown — the human-readable
    explanation plus, when present, the fenced ```json ``plan`` block and
    any appended pre-images — passed through verbatim so the review-queue
    app's diff view has something real to render without this module
    needing its own proposal-body parser (that belongs with the curator,
    SPEC-206, which writes the format this reads).
    """

    permalink: str
    title: str
    status: str
    created: str = ""
    body: str = ""


class ReviewQueueResult(BaseModel):
    """What one ``review_queue`` call answers: every pending proposal.

    ``decide_tool`` is filled in by :mod:`palaia_hub.gateway.memory_tools`
    (not by a :class:`VaultService` implementation) with this vault's own
    mounted ``review_decide`` tool name — the review-queue app's JS learns
    which tool to call back from this field rather than needing to know the
    vault's namespace itself (see that module's docstring).
    """

    proposals: list[ProposalSummary] = Field(default_factory=list)
    decide_tool: str = ""


class ReviewDecideResult(BaseModel):
    """What one ``review_decide`` call answers: the proposal's new status."""

    permalink: str
    status: str


class VaultServiceError(RuntimeError):
    """Raised by a :class:`VaultService` implementation for a caller-facing failure.

    Tool wrappers in :mod:`palaia_hub.gateway.memory_tools` catch this and
    turn it into a tool-level error result (``ToolResult(is_error=True)``)
    rather than letting it propagate as an uncaught exception.
    """


class VaultService(Protocol):
    """What the memory tool family needs from a vault, and nothing else.

    Every method is async so both an in-process implementation (direct
    filesystem/index access) and a future out-of-process one (e.g. behind an
    internal RPC) satisfy this protocol without changing the tools built on
    top of it. Implementations raise :class:`VaultServiceError` for
    caller-facing failures (not found, ambiguous, invalid); anything else
    propagates as an unexpected error.
    """

    async def search(self, query: str, *, limit: int = 10) -> SearchResponse:
        """Return notes matching ``query``, best match first.

        The response carries the hits *and* how they were produced (which
        channel matched each hit, which mode actually ran, whether it
        degraded) — see :class:`SearchResponse`.
        """
        ...

    async def read(self, permalink: str) -> NoteRecord:
        """Return the full note identified by ``permalink``."""
        ...

    async def write(
        self,
        title: str,
        body: str,
        *,
        folder: str = "",
        type: str = "note",  # noqa: A002 - matches the vault-format field name
        tags: list[str] | None = None,
    ) -> NoteRecord:
        """Create a new note and return the stored record."""
        ...

    async def edit(
        self,
        permalink: str,
        *,
        body: str | None = None,
        append: str | None = None,
        tags: list[str] | None = None,
    ) -> NoteRecord:
        """Update an existing note's body (replace or append) and/or tags."""
        ...

    async def move(self, permalink: str, folder: str) -> NoteRecord:
        """Move a note to a different folder; permalink is stable across moves."""
        ...

    async def delete(self, permalink: str) -> bool:
        """Delete a note. Returns ``True`` if a note was deleted."""
        ...

    async def list_notes(self, *, folder: str = "") -> list[NoteSummary]:
        """List notes, optionally restricted to a folder.

        Named ``list_notes`` rather than ``list`` at the Python level: a
        method literally named ``list`` on this class would shadow the
        builtin for every subsequent annotation in the class body (mypy
        catches this — ``list[NoteSummary]`` below would resolve to the
        method, not ``builtins.list``). The MCP-visible tool name is still
        the base action ``"list"`` (:data:`MEMORY_TOOL_ACTIONS`); that
        mapping happens in ``memory_tools.py``, not here.
        """
        ...

    async def recent_activity(self, *, limit: int = 10) -> list[NoteSummary]:
        """Return the most recently modified notes, most recent first."""
        ...

    async def capture(
        self,
        *,
        what_it_concerns: str,
        why_keep: str,
        content: str,
        source: str | None = None,
    ) -> CaptureResult:
        """Drop a zero-friction capture into ``inbox/`` (format spec §7).

        ``what_it_concerns`` and ``why_keep`` are mandatory (never guessed
        at by an implementation). An exact-duplicate of an existing
        ``inbox/`` entry is acknowledged without creating a second file —
        see :class:`CaptureResult`.
        """
        ...

    async def inbox_status(self) -> InboxStatusResult:
        """Summarize ``inbox/``: uncurated count, oldest entry age, last capture."""
        ...

    async def similar_notes(
        self, title: str, body: str, *, exclude: str = ""
    ) -> list[SimilarNoteHit]:
        """Existing notes whose meaning is close to ``title``/``body`` (issue #187).

        Called by ``write``/``capture`` *after* the note was stored, to warn
        about a possible overlap or contradiction — never to block it. Only
        notes above the implementation's configured similarity threshold are
        returned, best first, at most three; ``exclude`` is the permalink of
        the note just written. An implementation that cannot measure a true
        similarity (no index, no vectors yet) returns ``[]`` rather than
        guessing, and one that fails returns ``[]`` too: this is advice on a
        write that already succeeded, and must never turn it into an error.
        """
        ...

    async def recall(
        self,
        *,
        query: str = "",
        ref: str = "",
        limit: int = 5,
        model: str = "",
    ) -> RecallResult:
        """Recall from a query or a ``memory://`` reference (SPEC-106).

        Unlike ``search``, which answers "what matches these words", recall
        answers "what should I be looking at": results are decay-ranked,
        per-model observation variants are resolved for ``model``, and value
        references are resolved to their current source values.
        """
        ...

    async def build_context(
        self,
        *,
        ref: str = "",
        query: str = "",
        depth: int = 2,
        timeframe: str = "",
        max_tokens: int = 4000,
        model: str = "",
    ) -> ContextResult:
        """Assemble a budgeted context package by walking relations (SPEC-106)."""
        ...

    async def review_queue(self) -> ReviewQueueResult:
        """List every ``review/`` note with ``type: proposal`` (format spec §8).

        ``decide_tool`` on the returned result is left empty here — the
        tool wrapper (:mod:`palaia_hub.gateway.memory_tools`) fills it in,
        since only it knows this vault's mounted namespace.
        """
        ...

    async def review_decide(self, permalink: str, decision: str) -> ReviewDecideResult:
        """Flip one proposal's ``status`` to ``decision`` (``"approved"`` or
        ``"rejected"``) — the human-decision half of format spec §8; the
        curator's later apply pass (SPEC-206, out of this SPEC's scope) is
        what moves an ``approved`` proposal on to ``applied``/``apply-failed``.

        Raises :class:`VaultServiceError` if ``permalink`` does not resolve,
        is not a ``type: proposal`` note, or is not currently ``status:
        proposed`` (format spec §8: "every apply run ends in a terminal
        status" — a decided proposal is not redecided).
        """
        ...
