"""Thin async MCP client simulator for the e2e scenarios.

SPEC-113 deliverable #2. Deliberately does not reimplement any MCP wire
protocol details — :class:`fastmcp.Client` already speaks streamable HTTP
against a real server URL, including the 2026-07-28 protocol-version
handshake nuance ``_e2e_server.py`` (SPEC-105) documented. This module wraps
it down to exactly the operations the scenarios need: connect, list tools,
call a tool and get back both the human-readable text and the structured
payload, and take a name+schema snapshot for drift detection.

Each :class:`SimulatedClient` carries its own MCP ``client_info`` (name +
version), so two simulated clients hitting the same gateway profile (or two
different profiles mounting the same vault) show up as genuinely distinct
MCP sessions — the mechanism S1 (SPEC-113) uses to play "client A" and
"client B" against one shared vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from mcp.types import Implementation, Tool


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    """One tool call's outcome: human text, structured payload, error flag."""

    text: str
    structured: Any | None
    is_error: bool


def tool_schema_snapshot(tools: list[Tool]) -> dict[str, Any]:
    """A comparable, order-independent snapshot of a tool list's names+schemas.

    Used by the golden ``tools/list`` snapshot test (SPEC-113 acceptance:
    "harness fails loudly on tool-schema drift") and reusable by any SPEC
    that wants the same drift check against its own tool surface.
    """
    return {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.inputSchema,
            "annotations": tool.annotations.model_dump() if tool.annotations else None,
        }
        for tool in tools
    }


class SimulatedClient:
    """One simulated MCP client session against a gateway profile URL.

    Usage::

        async with SimulatedClient(url, client_name="claude-code") as client:
            tools = await client.list_tools()
            result = await client.call_tool_ok("work_memory_write", {...})
    """

    def __init__(
        self,
        url: str,
        *,
        client_name: str = "simulated-client",
        client_version: str = "0.0.0",
        token: str | None = None,
    ) -> None:
        self._url = url
        self._client_info = Implementation(name=client_name, version=client_version)
        self._client: Client[Any] | None = None
        #: A `plt_...` bearer token (SPEC-108), for scenarios against a hub
        #: with auth enabled — fastmcp's `Client(auth=<str>)` wraps a plain
        #: string in `BearerAuth` itself, so this is just threaded through.
        self._token = token

    async def __aenter__(self) -> SimulatedClient:
        client: Client[Any] = Client(
            self._url, client_info=self._client_info, auth=self._token
        )
        await client.__aenter__()
        self._client = client
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client = self._client
        self._client = None
        if client is not None:
            await client.__aexit__(*exc_info)

    def _require_client(self) -> Client[Any]:
        if self._client is None:
            raise RuntimeError("SimulatedClient used outside 'async with'")
        return self._client

    async def list_tools(self) -> list[Tool]:
        return await self._require_client().list_tools()

    async def tool_names(self) -> set[str]:
        return {tool.name for tool in await self.list_tools()}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolCallResult:
        """Call a tool, never raising on a tool-level (``isError``) failure."""
        result = await self._require_client().call_tool(
            name, arguments or {}, raise_on_error=False
        )
        text = "".join(getattr(block, "text", "") for block in result.content)
        return ToolCallResult(
            text=text,
            structured=result.structured_content,
            is_error=bool(result.is_error),
        )

    async def call_tool_ok(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> ToolCallResult:
        """Call a tool and assert it did not return a tool-level error."""
        result = await self.call_tool(name, arguments)
        assert not result.is_error, f"{name} call failed: {result.text}"
        return result


__all__ = ["SimulatedClient", "ToolCallResult", "tool_schema_snapshot"]
