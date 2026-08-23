"""Standalone "remote upstream" MCP server for the gateway spike.

Run on its own port (`uv run python servers/remote_upstream.py`) to simulate
a third-party MCP server the gateway reaches over the network and mounts via
`FastMCP.as_proxy()` / `ProxyProvider` — the way palaia will mount
user-added connectors (MASTERPLAN §5.2).
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

remote_server = FastMCP(name="remote-upstream")


@remote_server.tool
def echo(text: str) -> str:
    """Echo text back, prefixed to prove the call round-tripped over the network."""
    return f"remote-upstream echo: {text}"


@remote_server.tool
def weather(city: str) -> str:
    """Fake weather lookup — stands in for a real third-party connector."""
    return f"remote-upstream weather: sunny in {city} (fixture data)"


if __name__ == "__main__":
    port = int(os.environ.get("REMOTE_UPSTREAM_PORT", "8811"))
    remote_server.run(transport="http", host="127.0.0.1", port=port)
