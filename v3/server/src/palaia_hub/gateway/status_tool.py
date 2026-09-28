"""``memory_status`` — can this connection use its memory, and which one?

Issue #524: agents concluded their memory was "unavailable" from start-up
notices or tool names they did not find, instead of checking. The hub-wide
``hub_status`` tool exists, but on its own mount (``/mcp/hub``), which a
client connected to its memory profile never sees. So every memory profile
carries one un-namespaced tool that answers, in one cheap call:

- which client and profile this connection is,
- each memory (vault) mounted here: whether this token may read and write
  it, the prefix its tools carry (``work_memory_``), how many notes it
  holds, and whether search is hybrid or full-text only (and why),
- the hub's version.

"Reachable" needs no probe of its own: the answer arriving *is* the proof.
The tool reads no note and runs no search (:meth:`~palaia_hub.gateway.
vault_protocol.VaultService.status`).

MASTERPLAN §4 rule 8 (MCP App?): no. The answer is read by the model to
decide what to do next; there is nothing to explore or select, so a plain
tool with structured output fits and an app would add nothing.

The curator profile never shows it: its middleware serves only the
curator's own actions and refuses anything else.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict

from .. import __version__
from .config import VaultMountConfig
from .vault_protocol import VaultService, VaultServiceError

TOOL_NAME = "memory_status"


class MemoryAccess(BaseModel):
    """One memory as this connection sees it."""

    model_config = ConfigDict(extra="forbid")

    memory: str
    purpose: str
    #: Every tool of this memory starts with this, e.g. ``work_memory_``.
    tool_prefix: str
    read: bool
    write: bool
    notes: int | None = None
    #: ``hybrid``, ``fulltext``, or ``unknown`` when the vault could not answer.
    search: str = "unknown"
    search_note: str = ""


class MemoryStatusResult(BaseModel):
    """What one ``memory_status`` call answers."""

    model_config = ConfigDict(extra="forbid")

    hub_version: str
    profile: str
    #: The client name the token was issued under; ``None`` on a connection
    #: that needs no token.
    client: str | None
    memories: list[MemoryAccess]


def _access(vault_key: str) -> tuple[bool, bool]:
    """(read, write) for the current call's token. No token means this mount
    requires none, and every action is allowed — the same rule
    :func:`palaia_hub.auth.enforcement.missing_scope_error` applies."""
    token = get_access_token()
    if token is None:
        return True, True
    scopes = set(token.scopes)
    return f"vault:{vault_key}:read" in scopes, f"vault:{vault_key}:write" in scopes


def _summary(result: MemoryStatusResult) -> str:
    who = f"as {result.client!r}" if result.client else "without a token"
    lines = [
        f"Connected to palaia {result.hub_version} {who}, profile {result.profile!r}. "
        "This answer came from the hub, so the connection works."
    ]
    if not result.memories:
        lines.append("No memory is mounted on this connection.")
    for memory in result.memories:
        rights = (
            "read and write"
            if memory.read and memory.write
            else "read only"
            if memory.read
            else "write only"
            if memory.write
            else "no access"
        )
        notes = f"{memory.notes} notes" if memory.notes is not None else "note count unavailable"
        search = {"hybrid": "hybrid search", "fulltext": "full-text search only"}.get(
            memory.search, "search mode unknown"
        )
        detail = f" ({memory.search_note})" if memory.search_note else ""
        lines.append(
            f"- {memory.memory}: {rights}, {notes}, {search}{detail}; "
            f"tools start with {memory.tool_prefix}"
        )
    return "\n".join(lines)


def register_memory_status(
    server: FastMCP,
    *,
    profile: str,
    vaults: Sequence[VaultMountConfig],
    services: Mapping[str, VaultService],
) -> None:
    """Add ``memory_status`` to one profile's server."""

    @server.tool(
        name=TOOL_NAME,
        description=(
            "Check which palaia memories this connection can use, before "
            "concluding that memory is unavailable. Returns, for each memory: "
            "whether you may read and write it, the prefix its tools carry, "
            "its note count and whether search is hybrid or full-text only. "
            "Cheap: reads no note and runs no search."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
    )
    async def memory_status() -> ToolResult:
        token = get_access_token()
        memories: list[MemoryAccess] = []
        for vault in vaults:
            read, write = _access(vault.key)
            entry = MemoryAccess(
                memory=vault.key,
                purpose=vault.purpose or "",
                tool_prefix=f"{vault.namespace}_",
                read=read,
                write=write,
            )
            service = services.get(vault.key)
            if service is not None:
                try:
                    status = await service.status()
                except VaultServiceError as exc:
                    entry.search_note = f"the vault could not report its status: {exc}"
                else:
                    entry.notes = status.notes
                    entry.search = status.search
                    entry.search_note = status.search_note
            memories.append(entry)
        result = MemoryStatusResult(
            hub_version=__version__,
            profile=profile,
            client=None if token is None else token.subject,
            memories=memories,
        )
        return ToolResult(content=_summary(result), structured_content=result.model_dump())


__all__ = ["TOOL_NAME", "MemoryAccess", "MemoryStatusResult", "register_memory_status"]
