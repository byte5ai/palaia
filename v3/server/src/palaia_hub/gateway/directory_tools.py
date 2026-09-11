"""Builds the session directory tool family as a mountable FastMCP server
(SPEC-402).

Deliverable #3: ``directory_register``/``directory_heartbeat``/
``directory_update``/``directory_list``/``directory_query``/
``directory_deregister``, following the stash tool family's established
patterns (:mod:`palaia_hub.gateway.stash_tools`) — consistency beats
invention:

- **Behavior annotations** on every tool (read-only vs. destructive vs.
  idempotent).
- **Alias absorption**: hosts/models self-report inconsistently, so
  ``platform`` also accepts ``client``, and ``agent_kind`` also accepts
  ``kind``/``role``. The published schema still shows only the canonical
  name.
- **Dual text/json output**: every tool returns a human-readable
  ``content`` string alongside its ``structured_content`` payload.
- **Own IDENTITY line**, distinct from memory/stash: this server's
  ``instructions`` open with "IDENTITY: this is the session directory —
  a live registry of connected agent sessions ... NOT memory and NOT the
  stash." so a calling model does not reach here for anything it should
  actually be writing to memory or stash.

Like the stash tool family (and unlike a vault's memory tools), the
directory tool family is not namespaced by mount — there is exactly one
directory per hub — so the six tool names below are already final;
:mod:`palaia_hub.gateway.build` mounts this server as-is, with no
``namespace=`` argument.

**The session secret never appears in a published schema's default or
description beyond "keep this"** — it is an ordinary string parameter (the
caller must have stored it from ``directory_register``'s result), not a
credential fastmcp itself handles, so there is nothing special to do at the
tool-definition level; the store/service layer is what enforces it
(:mod:`palaia_hub.directory.store`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, Field
from starlette.types import ASGIApp

from ..auth.enforcement import missing_directory_scope_error
from ..directory.models import DirectoryError, ReportedStatus, SessionStatus
from ..directory.service import DirectoryService
from ..directory.store import DEFAULT_TTL_SECONDS, MAX_TTL_SECONDS, MIN_TTL_SECONDS

DIRECTORY_TOOL_ACTIONS: tuple[str, ...] = (
    "directory_register",
    "directory_heartbeat",
    "directory_update",
    "directory_list",
    "directory_query",
    "directory_deregister",
)

DIRECTORY_IDENTITY = (
    "IDENTITY: this is the session directory — a live registry of connected "
    "agent sessions (presence and context: scope, host, platform, model, "
    "status), NOT memory and NOT the stash. Do not write facts, decisions "
    "or cache data here — those belong in the memory tools' write or the "
    "stash tools, respectively. Register once per session with "
    "directory_register, keep the returned session_secret for every later "
    "call on that handle (heartbeat/update/deregister) — nobody else can "
    "act on your session without it — and heartbeat periodically or your "
    "session will show as stale to everyone else."
)

SessionHandleParam = Annotated[
    str, Field(description="This session's handle, from directory_register's result.")
]
SessionSecretParam = Annotated[
    str,
    Field(description="This session's secret, from directory_register's result. Never shared."),
]
PlatformParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("platform", "client"),
        description=(
            "The client platform, e.g. claude-code, claude-desktop, claude-ai, "
            "codex, gemini, other. Free text, stored verbatim."
        ),
    ),
]
AgentKindParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("agent_kind", "kind", "role"),
        description="What kind of agent this is (e.g. 'coding assistant', 'reviewer').",
    ),
]


def _error_result(exc: DirectoryError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _scope_error(action: str) -> ToolResult | None:
    message = missing_directory_scope_error(action)
    return ToolResult(content=message, is_error=True) if message else None


def build_directory_server(
    service: DirectoryService, *, auth: AuthProvider | None = None
) -> FastMCP:
    """Build the session directory tool family, backed by ``service``."""
    server = FastMCP(name="palaia-directory", instructions=DIRECTORY_IDENTITY, auth=auth)

    def desc(detail: str) -> str:
        return f"{DIRECTORY_IDENTITY}\n\n{detail}"

    @server.tool(
        name="directory_register",
        description=desc(
            "Register this session with the directory. Returns a handle "
            "(stable for this registration's lifetime, safe to share for "
            "addressing) and a session_secret (keep it private — needed "
            "for every later heartbeat/update/deregister on this handle). "
            "ttl_seconds controls how long this session may go without a "
            "heartbeat before showing as stale to others (default "
            f"{DEFAULT_TTL_SECONDS:.0f}s; values outside {MIN_TTL_SECONDS:.0f}s to "
            f"{MAX_TTL_SECONDS:.0f}s are clamped to that range)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def directory_register(
        scope: Annotated[
            str, Field(description="Free text: what this session is working on right now.")
        ] = "",
        host: Annotated[str, Field(description="This session's machine/host identifier.")] = "",
        platform: PlatformParam = "",
        agent_kind: AgentKindParam = "",
        model: Annotated[
            str,
            Field(
                description=("Model name, self-reported verbatim (display only, never trusted).")
            ),
        ] = "",
        capabilities: Annotated[
            list[str] | None, Field(description="Free-text capability tags this session offers.")
        ] = None,
        ttl_seconds: Annotated[
            float,
            Field(
                description=(
                    "Seconds without a heartbeat before this session goes stale "
                    f"({MIN_TTL_SECONDS:.0f} to {MAX_TTL_SECONDS:.0f}; out-of-range values "
                    "are clamped)."
                )
            ),
        ] = DEFAULT_TTL_SECONDS,
    ) -> ToolResult:
        if (err := _scope_error("directory_register")) is not None:
            return err
        result = await service.register(
            scope=scope,
            host=host,
            platform=platform,
            agent_kind=agent_kind,
            model=model,
            capabilities=capabilities or [],
            ttl_seconds=ttl_seconds,
        )
        text = (
            f"registered {result.session.handle} (platform={platform or 'unset'}); "
            "keep session_secret private — it is not shown again"
        )
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="directory_heartbeat",
        description=desc(
            "Keep this session marked active/idle (not stale) by bumping its "
            "last-seen time. Requires the handle and session_secret this "
            "session registered with; a wrong secret is refused."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def directory_heartbeat(
        handle: SessionHandleParam, session_secret: SessionSecretParam
    ) -> ToolResult:
        if (err := _scope_error("directory_heartbeat")) is not None:
            return err
        try:
            result = await service.heartbeat(handle, session_secret)
        except DirectoryError as exc:
            return _error_result(exc)
        return ToolResult(content=f"heartbeat ok for {handle}", structured_content=result)

    @server.tool(
        name="directory_update",
        description=desc(
            "Update this session's self-reported scope/status/capabilities. "
            "status is 'active' or 'idle' (never 'stale' — that is always "
            "computed from the heartbeat clock, not settable). Any field "
            "left unset keeps its current value. Also counts as a "
            "heartbeat. Requires the handle and session_secret this session "
            "registered with."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def directory_update(
        handle: SessionHandleParam,
        session_secret: SessionSecretParam,
        scope: Annotated[
            str | None, Field(description="New scope text, or unset to keep it.")
        ] = None,
        status: Annotated[
            ReportedStatus | None,
            Field(description="'active' or 'idle', or unset to keep it. Never 'stale'."),
        ] = None,
        capabilities: Annotated[
            list[str] | None,
            Field(description="Replaces the full capability tag list, or unset to keep it."),
        ] = None,
    ) -> ToolResult:
        if (err := _scope_error("directory_update")) is not None:
            return err
        try:
            result = await service.update(
                handle, session_secret, scope=scope, status=status, capabilities=capabilities
            )
        except DirectoryError as exc:
            return _error_result(exc)
        return ToolResult(content=f"updated {handle}", structured_content=result)

    @server.tool(
        name="directory_list",
        description=desc(
            "List every session in the directory, most recently registered "
            "first. Optional filters: status ('active'/'idle'/'stale'), "
            "platform (exact match), capability (must be one of the "
            "session's tags)."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def directory_list(
        status: Annotated[
            SessionStatus | None, Field(description="Filter by effective status.")
        ] = None,
        platform: Annotated[
            str | None, Field(description="Filter by exact platform match.")
        ] = None,
        capability: Annotated[
            str | None, Field(description="Filter to sessions carrying this capability tag.")
        ] = None,
    ) -> ToolResult:
        if (err := _scope_error("directory_list")) is not None:
            return err
        result = await service.list(status=status, platform=platform, capability=capability)
        plural = "s" if len(result.sessions) != 1 else ""
        text = f"{len(result.sessions)} session{plural} in the directory"
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="directory_query",
        description=desc(
            "Find sessions by a substring of their self-reported scope "
            "(case-insensitive — e.g. 'who is working on repo X') and/or a "
            "capability tag. Both filters optional; neither given returns "
            "every session."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def directory_query(
        scope_contains: Annotated[
            str | None, Field(description="Case-insensitive substring to match against scope.")
        ] = None,
        capability: Annotated[
            str | None, Field(description="Filter to sessions carrying this capability tag.")
        ] = None,
    ) -> ToolResult:
        if (err := _scope_error("directory_query")) is not None:
            return err
        result = await service.query(scope_contains=scope_contains, capability=capability)
        plural = "s" if len(result.sessions) != 1 else ""
        text = f"{len(result.sessions)} matching session{plural}"
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="directory_deregister",
        description=desc(
            "Remove this session from the directory. Irreversible. "
            "Requires the handle and session_secret this session registered "
            "with; already-gone handles report deregistered=false rather "
            "than an error."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def directory_deregister(
        handle: SessionHandleParam, session_secret: SessionSecretParam
    ) -> ToolResult:
        if (err := _scope_error("directory_deregister")) is not None:
            return err
        try:
            result = await service.deregister(handle, session_secret)
        except DirectoryError as exc:
            return _error_result(exc)
        text = f"deregistered {handle}" if result.deregistered else f"no session at {handle}"
        return ToolResult(content=text, structured_content=result)

    return server


@dataclass
class DirectoryGatewayASGI:
    """The directory server's mountable surface, mirroring
    :class:`palaia_hub.gateway.stash_tools.StashGatewayASGI`'s shape for the
    one hub-level server this module builds (not per-profile, since there
    is exactly one directory per hub). ``lifespan`` MUST be combined into
    whatever ASGI app ``app`` is mounted under, same caveat as stash.
    """

    app: ASGIApp
    lifespan: Any
    #: The ``FastMCP`` behind ``app`` — what
    #: :func:`palaia_hub.auth.policy.check_hub_mount_auth_policy` inspects.
    server: FastMCP


def build_directory_gateway(
    service: DirectoryService, *, auth: AuthProvider | None = None
) -> DirectoryGatewayASGI:
    """Build the directory server and its mountable ASGI app + lifespan,
    ready for ``app.mount("/mcp/directory", ...)`` (see
    :mod:`palaia_hub.app`)."""
    server = build_directory_server(service, auth=auth)
    asgi_app = server.http_app(path="/")
    return DirectoryGatewayASGI(app=asgi_app, lifespan=asgi_app.lifespan, server=server)


__all__ = [
    "DIRECTORY_IDENTITY",
    "DIRECTORY_TOOL_ACTIONS",
    "DirectoryGatewayASGI",
    "build_directory_gateway",
    "build_directory_server",
]
