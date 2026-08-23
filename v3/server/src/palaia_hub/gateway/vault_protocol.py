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
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

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


class NoteSummary(BaseModel):
    """Enough to list, browse, or pick a note without fetching its body."""

    permalink: str
    title: str
    type: str = "note"
    tags: list[str] = Field(default_factory=list)
    folder: str = ""
    modified: str = ""


class NoteRecord(NoteSummary):
    """A full note: everything in :class:`NoteSummary` plus its body."""

    body: str = ""
    created: str = ""


class SearchHit(BaseModel):
    """One search result: a note plus why it matched."""

    permalink: str
    title: str
    snippet: str = ""
    score: float = 0.0


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

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Return notes matching ``query``, best match first."""
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
