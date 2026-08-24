"""The curator-scope middleware: policy enforcement at the gateway (SPEC-206).

One fastmcp :class:`~fastmcp.server.middleware.Middleware`, attached to the
curator profile's own :class:`~fastmcp.FastMCP` server (see
:mod:`palaia_hub.curator.profile`), doing two things and nothing else:

1. **Narrows the tool surface.** ``tools/list`` on a curator profile returns
   only the actions in :data:`~palaia_hub.curator.policy.CURATOR_TOOL_ACTIONS`,
   and a ``tools/call`` for anything else is refused — even though the vault
   tool server mounted underneath is the very same object the ordinary
   profile mounts. Sharing that object is what keeps one definition of each
   tool; the profile's own middleware is what makes the *profile* narrower.
2. **Applies the per-call guards** of :func:`~palaia_hub.curator.policy.
   rejection_for` — replacing operations, overwrite semantics, ``inbox/``
   writes, ``review/`` edits, and writes with no capture provenance.

A refusal comes back as ``ToolResult(is_error=True)``, the same shape the
memory tools already use for a missing scope (SPEC-108) — an MCP-level tool
error the model reads and reacts to, not a transport failure. The SPEC's own
prompt tells the session as much: "a rejected call is information, not an
obstacle".
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult

from .policy import CURATOR_TOOL_ACTIONS, ActiveCaptures, rejection_for

logger = logging.getLogger("palaia_hub.curator.middleware")


class CuratorScopeMiddleware(Middleware):
    """Enforces the curator's tool surface and write guards on one profile.

    Args:
        tool_actions: ``{tool name as the client sees it: base action}`` for
            every tool this profile exposes — built by
            :func:`palaia_hub.curator.profile.curator_tool_actions` from the
            profile's vault namespaces, so a renamed tool
            (``tool_renames``) is still mapped to the action it really is.
            A tool name absent from this mapping is refused: an unmapped
            name is one this middleware cannot classify, and the policy is
            fail-closed.
        active_captures: the in-process capture binding
            (:class:`~palaia_hub.curator.policy.ActiveCaptures`) the runner
            registers each session against. Omitted, provenance checking is
            shape-only — see that class's docstring.
    """

    def __init__(
        self,
        tool_actions: Mapping[str, str],
        *,
        active_captures: ActiveCaptures | None = None,
    ) -> None:
        self._tool_actions = dict(tool_actions)
        self._active_captures = active_captures or ActiveCaptures()

    @property
    def active_captures(self) -> ActiveCaptures:
        return self._active_captures

    def action_for(self, tool_name: str) -> str | None:
        """The base action ``tool_name`` maps to, or ``None`` if unknown here."""
        return self._tool_actions.get(tool_name)

    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(
            name
            for name, action in self._tool_actions.items()
            if action in CURATOR_TOOL_ACTIONS
        )

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        allowed = self.allowed_tool_names()
        return [tool for tool in tools if tool.name in allowed]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        arguments = context.message.arguments or {}
        action = self.action_for(name)
        if action is None:
            return _refusal(
                f"rejected: {name!r} is not a tool this curator profile serves. "
                f"The curator's surface is {', '.join(CURATOR_TOOL_ACTIONS)}, "
                "on this vault's own tools only."
            )
        message = rejection_for(
            action, arguments, expected_captures=self._active_captures.current()
        )
        if message is not None:
            logger.info(
                "curator guard refused %s (%s)", name, message.split(".", 1)[0]
            )
            return _refusal(message)
        return await call_next(context)


def _refusal(message: str) -> ToolResult:
    return ToolResult(content=message, is_error=True)


__all__ = ["CuratorScopeMiddleware"]
