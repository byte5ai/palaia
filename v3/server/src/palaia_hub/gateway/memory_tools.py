"""Builds one vault's memory tool family as a mountable FastMCP server.

Deliverable #2 of SPEC-105: search / read / write / edit / move / delete /
list / recent_activity, mounted once per configured vault (see
:mod:`palaia_hub.gateway.build`). Deliverable #4 (tool ergonomics) is
implemented here directly on each tool:

- **Behavior annotations** (``readOnlyHint``/``destructiveHint``/
  ``idempotentHint``) on every tool.
- **Alias absorption**: ``search``'s ``query`` accepts ``q``/``text``;
  every ``folder`` parameter accepts ``dir``/``path`` — the two alias
  groups SPEC-105 names explicitly, via pydantic ``AliasChoices``. The
  published input schema still shows only the canonical name (verified in
  ``tests/gateway/test_memory_tools.py``); the aliases are absorbed
  silently, not documented as alternatives, so the schema an agent reads
  stays uncluttered.
- **Dual text/json output**: every tool returns a ``ToolResult`` with a
  human-readable ``content`` string and a ``structured_content`` payload
  (the underlying pydantic result model) side by side in the same
  response — not a client-selectable mode.
- **Leading purpose line**: every tool description starts with the vault's
  ``purpose`` string verbatim, so a client's tool picker always shows why
  this vault exists first (MASTERPLAN §5.2 disambiguation-from-the-tool-
  surface requirement).
- **IDENTITY instructions + `ai_assistant_guide` resource**: the server's
  ``instructions`` open with an ``IDENTITY:`` line naming the vault, and an
  ``ai_assistant_guide`` resource gives the model a short workflow guide
  (research/basic-memory.md §7).

Errors from the :class:`VaultService` (not-found, etc.) become
``ToolResult(is_error=True, ...)`` rather than an uncaught exception, per
MCP convention (isError, not a transport-level failure).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, BaseModel, Field

from ..auth.enforcement import missing_scope_error
from .config import VaultMountConfig
from .vault_protocol import NoteRecord, NoteSummary, SearchHit, VaultService, VaultServiceError

# --- alias-absorbing parameter types ---------------------------------------
# SPEC-105 deliverable #4 names these two alias groups explicitly: a query
# parameter that also accepts q/text, and a folder parameter that also
# accepts dir/path. AliasChoices only affects *validation* (what an
# incoming call is allowed to name the field) — the tool's published input
# schema still shows just "query"/"folder" (see docstring above), so the
# canonical shape a well-behaved client sees stays clean while a client
# that guesses "q" or "path" still succeeds.
QueryParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("query", "q", "text"),
        description="Search text.",
    ),
]
FolderParam = Annotated[
    str,
    Field(
        default="",
        validation_alias=AliasChoices("folder", "dir", "path"),
        description="Folder to scope to. Empty means the whole vault.",
    ),
]


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]


class ListResult(BaseModel):
    folder: str
    notes: list[NoteSummary]


class RecentActivityResult(BaseModel):
    notes: list[NoteSummary]


class DeleteResult(BaseModel):
    permalink: str
    deleted: bool


def _error_result(exc: VaultServiceError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _note_result(action: str, note: NoteRecord) -> ToolResult:
    text = f"{action}: {note.title!r} ({note.permalink})"
    return ToolResult(content=text, structured_content=note)


def vault_identity_block(vault: VaultMountConfig) -> str:
    """The IDENTITY line + short workflow guide for one vault.

    Used both for that vault's own tool server's ``instructions`` (a client
    that connects to the vault server directly — e.g. in tests — sees this)
    and, concatenated across every vault a profile mounts, for that
    profile's own ``instructions`` (what a real client connecting to
    ``/mcp/<profile>`` actually receives at ``initialize`` — ``mount()``
    does not propagate a mounted server's ``instructions`` to its parent,
    so the profile builder in ``build.py`` composes this explicitly rather
    than leaving real clients with no IDENTITY line at all).
    """
    identity = f"IDENTITY: this is the {vault.name!r} memory vault. {vault.purpose}"
    return (
        f"{identity}\n"
        "Search before writing — check whether this already exists before "
        "creating a new note. Use recent_activity to catch up on what "
        "changed since you last looked. Read the ai_assistant_guide "
        "resource for the full tool-by-tool workflow."
    )


def build_vault_server(vault: VaultMountConfig, service: VaultService) -> FastMCP:
    """Build the memory tool family for one vault, backed by ``service``.

    The returned server's tools are named exactly the eight base action
    names (``search``, ``read``, ...) — callers mount it with
    ``namespace=vault.namespace`` (see :mod:`palaia_hub.gateway.build`),
    which is what actually produces the vault-identity-carrying final name
    (``work_memory_search``). Building the tool names here without any
    namespace baked in keeps this function reusable across profiles: the
    same server object mounts into every profile that includes this vault.
    """
    purpose = vault.purpose
    server = FastMCP(
        name=f"palaia-vault-{vault.key}",
        instructions=vault_identity_block(vault),
    )

    def desc(detail: str) -> str:
        return f"{purpose}\n\n{detail}"

    def scope_error(action: str) -> ToolResult | None:
        """``None`` if this call's token (if any) covers ``action``; else a
        ready-to-return ``ToolResult(is_error=True)`` naming the missing
        scope (SPEC-108 — see :func:`palaia_hub.auth.enforcement.
        missing_scope_error` for what "if any" means here).
        """
        message = missing_scope_error(vault.key, action)
        return ToolResult(content=message, is_error=True) if message else None

    @server.tool(
        name="search",
        description=desc("Search this vault's notes. Returns best matches first."),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def search(query: QueryParam, limit: int = 10) -> ToolResult:
        if (err := scope_error("search")) is not None:
            return err
        hits = await service.search(query, limit=limit)
        text = (
            f"{len(hits)} match(es) for {query!r}: "
            + ", ".join(f"{h.title!r} ({h.permalink})" for h in hits)
            if hits
            else f"no matches for {query!r}"
        )
        return ToolResult(content=text, structured_content=SearchResult(query=query, hits=hits))

    @server.tool(
        name="read",
        description=desc("Read one note in full by its permalink."),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def read(permalink: str) -> ToolResult:
        if (err := scope_error("read")) is not None:
            return err
        try:
            note = await service.read(permalink)
        except VaultServiceError as exc:
            return _error_result(exc)
        return ToolResult(content=note.body, structured_content=note)

    @server.tool(
        name="write",
        description=desc("Create a new note in this vault."),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def write(
        title: str,
        body: str,
        folder: FolderParam = "",
        type: str = "note",  # noqa: A002 - matches the vault-format field name
        tags: list[str] | None = None,
    ) -> ToolResult:
        if (err := scope_error("write")) is not None:
            return err
        try:
            note = await service.write(title, body, folder=folder, type=type, tags=tags)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_result("created", note)

    @server.tool(
        name="edit",
        description=desc("Update an existing note's body and/or tags."),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=False
        ),
    )
    async def edit(
        permalink: str,
        body: str | None = None,
        append: str | None = None,
        tags: list[str] | None = None,
    ) -> ToolResult:
        if (err := scope_error("edit")) is not None:
            return err
        try:
            note = await service.edit(permalink, body=body, append=append, tags=tags)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_result("updated", note)

    @server.tool(
        name="move",
        description=desc("Move a note to a different folder. Its permalink never changes."),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True
        ),
    )
    async def move(permalink: str, folder: FolderParam = "") -> ToolResult:
        if (err := scope_error("move")) is not None:
            return err
        try:
            note = await service.move(permalink, folder)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_result("moved", note)

    @server.tool(
        name="delete",
        description=desc("Delete a note by permalink. Irreversible outside git history."),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True
        ),
    )
    async def delete(permalink: str) -> ToolResult:
        if (err := scope_error("delete")) is not None:
            return err
        deleted = await service.delete(permalink)
        text = f"deleted {permalink!r}" if deleted else f"nothing to delete at {permalink!r}"
        return ToolResult(
            content=text, structured_content=DeleteResult(permalink=permalink, deleted=deleted)
        )

    @server.tool(
        name="list",
        description=desc("List notes in this vault, optionally scoped to a folder."),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def list_notes(folder: FolderParam = "") -> ToolResult:
        if (err := scope_error("list")) is not None:
            return err
        notes = await service.list_notes(folder=folder)
        text = f"{len(notes)} note(s)" + (f" in {folder!r}" if folder else "")
        return ToolResult(content=text, structured_content=ListResult(folder=folder, notes=notes))

    @server.tool(
        name="recent_activity",
        description=desc("The most recently modified notes, most recent first."),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def recent_activity(limit: int = 10) -> ToolResult:
        if (err := scope_error("recent_activity")) is not None:
            return err
        notes = await service.recent_activity(limit=limit)
        text = f"{len(notes)} recently modified note(s)"
        return ToolResult(content=text, structured_content=RecentActivityResult(notes=notes))

    @server.resource(
        f"guide://{vault.key}/ai_assistant_guide",
        name="ai_assistant_guide",
        mime_type="text/markdown",
    )
    def ai_assistant_guide() -> str:
        return (
            f"# {vault.name} memory vault — assistant guide\n\n"
            f"{purpose}\n\n"
            "## Workflow\n"
            "1. **search** first — check whether this already exists before writing.\n"
            "2. **read** a hit's full body before deciding to edit vs. write new.\n"
            "3. **write** a new note when nothing matches; **edit** (replace or "
            "append) when something does.\n"
            "4. **list** / **recent_activity** to browse or catch up without a "
            "specific query.\n"
            "5. **move** relocates a note without changing its identity "
            "(permalink); **delete** removes it.\n\n"
            "## Parameter notes\n"
            "`search`'s query and every `folder` parameter accept a few common "
            "misnamings (e.g. `q`, `dir`, `path`) — use the documented name "
            "shown in the tool schema when in doubt."
        )

    return server


__all__ = ["build_vault_server", "vault_identity_block"]

# Re-exported for callers that want the result-model shapes without reaching
# into this module's internals (e.g. tests asserting structured_content).
_RESULT_MODELS: dict[str, type[Any]] = {
    "search": SearchResult,
    "list": ListResult,
    "recent_activity": RecentActivityResult,
    "delete": DeleteResult,
}
