"""In-process "local" server for the gateway spike.

Simulates a first-party palaia component (e.g. the memory engine) that runs
in the same Python process as the gateway and is mounted directly — no
network hop, no ProxyProvider.
"""

from __future__ import annotations

from fastmcp import FastMCP

local_server = FastMCP(name="local-memory")


@local_server.tool
def memory_search(query: str) -> str:
    """Search the (fake) local memory vault for a query string."""
    return f"local-memory: 2 hits for {query!r} (fixture data, spike only)"


@local_server.tool
def memory_write(note: str) -> str:
    """Write a note into the (fake) local memory vault."""
    return f"local-memory: stored note ({len(note)} chars)"
