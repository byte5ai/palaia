"""Semantic tool routing (SPEC-305 deliverable #4, MASTERPLAN §5.2): a
profile can expose ``find_tool``/``invoke_tool`` instead of its full tool
surface, for a tool collection too large for a client's own picker.

Off by default (:class:`~.config.ProfileConfig.semantic_routing`), and
marked experimental everywhere the dashboard shows it — this is a real
change in what a connecting client sees, never a hub-wide default.

:func:`build_semantic_routing_server` is handed the profile's already-fully
-built ``FastMCP`` instance (every vault mounted, every rename applied,
every ``hidden_tools`` entry disabled — see ``gateway/build.py``) and wraps
it: the returned server is what actually gets served under the profile's
path; the server it wraps is never itself exposed over ASGI, so "the full
surface is absent" (SPEC-305's acceptance criterion) holds — a client sees
exactly two tools, backed by the profile's *real* tool list rather than a
second, hand-maintained copy of it.

The matching in :func:`find_tool` is a plain keyword-overlap score, not an
embedding search — good enough to point at the right tool by name/
description overlap, and it needs no extra dependency, network call, or
index to keep in sync with the profile's actual tools (which can change at
runtime, see ``gateway/dynamic.py``). A future SPEC can swap the scoring
function for something smarter without touching the two tools' contract.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError, ToolError
from fastmcp.tools.base import Tool, ToolResult

from .config import ProfileConfig

DEFAULT_FIND_LIMIT = 5


def _score(query: str, tool: Tool) -> int:
    """Plain keyword overlap between ``query`` and a tool's name/description.

    Every query word contributes once per occurrence in the haystack; a
    query that appears verbatim in the tool's name is boosted heavily, so
    an exact/near-exact name match (the common case: a client that already
    half-remembers the tool it wants) always sorts first.
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return 0
    haystack = f"{tool.name} {tool.description or ''}".lower()
    score = sum(haystack.count(word) for word in words)
    if query.strip().lower() in tool.name.lower():
        score += 10
    return score


def build_semantic_routing_server(profile: ProfileConfig, full_server: FastMCP) -> FastMCP:
    """The ``find_tool``/``invoke_tool`` router served in place of ``full_server``.

    Args:
        profile: the profile this router is built for (only its ``path``
            is used, for naming/instructions).
        full_server: the profile's fully-built ``FastMCP`` instance — every
            vault/stash tool it would otherwise expose directly. Kept
            alive by closure; never mounted or served on its own.

    The router carries ``full_server``'s own ``auth`` (issue #315): it is
    the surface actually served, so the profile's token verifier has to sit
    on *it* or the profile silently goes unauthenticated the moment
    ``semantic_routing`` is switched on. Middleware is deliberately not
    copied — ``full_server.call_tool`` (what ``invoke_tool`` delegates to)
    already runs the profile's middleware chain, so copying it onto the
    router would apply every policy twice per call.
    """
    router: FastMCP = FastMCP(
        name=f"palaia-gateway-{profile.path}-router",
        auth=full_server.auth,
        instructions=(
            "IDENTITY: this is a tool router, not a memory vault directly. "
            "It stands in for a large tool collection: call find_tool with "
            "what you are trying to do, in your own words, to see which "
            "real tools match; then call invoke_tool with the exact name "
            "one of those matches returned, and its arguments, to run it. "
            "The full tool surface is intentionally not listed here."
        ),
    )

    @router.tool(
        name="find_tool",
        description=(
            "Search this profile's real tools by plain-language description of what "
            "you want to do. Returns the closest matches — each with its exact name "
            "and input schema, ready to pass to invoke_tool."
        ),
    )
    async def find_tool(query: str, limit: int = DEFAULT_FIND_LIMIT) -> ToolResult:
        tools = await full_server.list_tools()
        ranked = sorted(tools, key=lambda t: _score(query, t), reverse=True)
        matches = [t for t in ranked if _score(query, t) > 0][: max(1, limit)]
        payload = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in matches
        ]
        if not payload:
            text = f"No tool matched {query!r}. This profile exposes {len(tools)} tool(s) in total."
        else:
            text = "\n".join(f"- {m['name']}: {m['description']}" for m in payload)
        return ToolResult(content=text, structured_content={"matches": payload})

    @router.tool(
        name="invoke_tool",
        description=(
            "Call one of this profile's real tools, by the exact name find_tool "
            "returned, with that tool's arguments."
        ),
    )
    async def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        try:
            return await full_server.call_tool(name, arguments or {})
        except (ToolError, NotFoundError) as exc:
            return ToolResult(content=str(exc), is_error=True)

    return router


__all__ = ["build_semantic_routing_server"]
