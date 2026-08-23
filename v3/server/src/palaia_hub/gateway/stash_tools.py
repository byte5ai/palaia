"""Builds the stash tool family as a mountable FastMCP server (SPEC-202).

Deliverable #2: ``stash_set``/``stash_get``/``stash_del``/``stash_list``/
``stash_status``, following the memory tool family's established patterns
(:mod:`palaia_hub.gateway.memory_tools`) — consistency beats invention:

- **Behavior annotations** on every tool (read-only vs. destructive vs.
  idempotent), same as the memory family.
- **Alias absorption**: ``namespace`` also accepts ``ns``/``scope``; ``key``
  also accepts ``name``/``id``; ``value`` also accepts ``data``/``payload``.
  The published schema still shows only the canonical name.
- **Dual text/json output**: every tool returns a human-readable
  ``content`` string alongside its ``structured_content`` payload.
- **Own IDENTITY line**, distinct from a vault's: this server's
  ``instructions`` open with "IDENTITY: this is the stash — cache for
  data, NOT memory. Knowledge belongs in memory tools, not here." so a
  calling model that reaches for stash to save a fact it should remember
  sees the boundary stated up front, not just in a description.

Unlike a vault's memory tools, the stash tool family is not namespaced by
mount (there is exactly one stash per hub, not one per vault) — the five
tool names here are already final; :mod:`palaia_hub.gateway.build` mounts
this server as-is, with no ``namespace=`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, Field
from starlette.types import ASGIApp

from ..auth.enforcement import missing_stash_scope_error
from ..stash.models import StashError
from ..stash.service import StashService

STASH_TOOL_ACTIONS: tuple[str, ...] = (
    "stash_set",
    "stash_get",
    "stash_del",
    "stash_list",
    "stash_status",
)

STASH_IDENTITY = (
    "IDENTITY: this is the stash — a structured cross-session cache. Use it "
    "for data you need to survive between sessions but that is disposable: "
    "job state, a rate-limit counter, a work-in-progress draft, dedup "
    "markers. It is NOT memory: anything worth remembering — a fact, a "
    "decision, a preference, a rule — belongs in the memory tools' write, "
    "not here. Entries expire (TTL) and can be evicted under the size "
    "budget (least-recently-accessed first); never rely on a stash entry "
    "surviving indefinitely."
)

NamespaceParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("namespace", "ns", "scope"),
        description="The cache namespace this key lives in.",
    ),
]
KeyParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("key", "name", "id"),
        description="The entry's key within its namespace.",
    ),
]
ValueParam = Annotated[
    Any,
    Field(
        validation_alias=AliasChoices("value", "data", "payload"),
        description="JSON-serializable value to store.",
    ),
]


def _error_result(exc: StashError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _scope_error(action: str) -> ToolResult | None:
    message = missing_stash_scope_error(action)
    return ToolResult(content=message, is_error=True) if message else None


def build_stash_server(service: StashService) -> FastMCP:
    """Build the stash tool family, backed by ``service``."""
    server = FastMCP(name="palaia-stash", instructions=STASH_IDENTITY)

    def desc(detail: str) -> str:
        return f"{STASH_IDENTITY}\n\n{detail}"

    @server.tool(
        name="stash_set",
        description=desc(
            "Write a value into the stash under namespace/key. Optional "
            "ttl_seconds is the hard expiry; optional stale_after_seconds "
            "marks the entry stale (still returned by stash_get, flagged) "
            "before that. Overwrites any existing value at the same key."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def stash_set(
        namespace: NamespaceParam,
        key: KeyParam,
        value: ValueParam,
        ttl_seconds: Annotated[
            float | None, Field(description="Hard expiry in seconds from now. None = no expiry.")
        ] = None,
        stale_after_seconds: Annotated[
            float | None,
            Field(description="Seconds from now after which the entry is marked stale."),
        ] = None,
    ) -> ToolResult:
        if (err := _scope_error("stash_set")) is not None:
            return err
        try:
            result = await service.set(
                namespace,
                key,
                value,
                ttl_seconds=ttl_seconds,
                stale_after_seconds=stale_after_seconds,
            )
        except StashError as exc:
            return _error_result(exc)
        text = f"stashed {namespace}/{key} ({result.size_bytes} bytes)"
        if result.evicted:
            text += f"; evicted to stay within budget: {', '.join(result.evicted)}"
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="stash_get",
        description=desc(
            "Read a value by namespace/key. Bumps the entry's last-accessed "
            "time (relevant to LRU eviction). Hard-expired entries read as "
            "not found; entries past their stale_after_seconds are still "
            "returned with stale=true."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False),
    )
    async def stash_get(namespace: NamespaceParam, key: KeyParam) -> ToolResult:
        if (err := _scope_error("stash_get")) is not None:
            return err
        result = await service.get(namespace, key)
        if not result.found:
            text = f"no entry at {namespace}/{key}"
        else:
            assert result.entry is not None
            stale_note = " (stale)" if result.entry.stale else ""
            text = f"{namespace}/{key}{stale_note}: {result.entry.value!r}"
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="stash_del",
        description=desc("Delete an entry by namespace/key. Irreversible."),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def stash_del(namespace: NamespaceParam, key: KeyParam) -> ToolResult:
        if (err := _scope_error("stash_del")) is not None:
            return err
        result = await service.delete(namespace, key)
        text = (
            f"deleted {namespace}/{key}"
            if result.deleted
            else f"nothing to delete at {namespace}/{key}"
        )
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="stash_list",
        description=desc(
            "List every entry in a namespace, most recently updated first. "
            "Does not count as an access for LRU purposes."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def stash_list(namespace: NamespaceParam) -> ToolResult:
        if (err := _scope_error("stash_list")) is not None:
            return err
        result = await service.list(namespace)
        plural = "y" if len(result.entries) == 1 else "ies"
        text = f"{len(result.entries)} entr{plural} in {namespace!r}"
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="stash_status",
        description=desc(
            "Overall stash health: total entries, total bytes used, the "
            "configured size budget, and a per-namespace entry count."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def stash_status() -> ToolResult:
        if (err := _scope_error("stash_status")) is not None:
            return err
        result = await service.status()
        text = (
            f"{result.total_entries} entries, "
            f"{result.total_bytes}/{result.budget_bytes} bytes used"
        )
        return ToolResult(content=text, structured_content=result)

    return server


@dataclass
class StashGatewayASGI:
    """The stash server's mountable surface, mirroring
    :class:`palaia_hub.gateway.build.GatewayASGI`'s shape for the one
    hub-level server this module builds (not per-profile, since there is
    exactly one stash per hub). ``lifespan`` MUST be combined into whatever
    ASGI app ``app`` is mounted under, same caveat as the vault gateway.
    """

    app: ASGIApp
    lifespan: Any


def build_stash_gateway(service: StashService) -> StashGatewayASGI:
    """Build the stash server and its mountable ASGI app + lifespan, ready
    for ``app.mount("/mcp/stash", ...)`` (see :mod:`palaia_hub.app`)."""
    server = build_stash_server(service)
    asgi_app = server.http_app(path="/")
    return StashGatewayASGI(app=asgi_app, lifespan=asgi_app.lifespan)


__all__ = [
    "STASH_IDENTITY",
    "STASH_TOOL_ACTIONS",
    "StashGatewayASGI",
    "build_stash_gateway",
    "build_stash_server",
]
