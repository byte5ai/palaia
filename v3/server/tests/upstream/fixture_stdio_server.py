"""A real, standalone FastMCP server used as a ``stdio`` upstream fixture.

Run as a subprocess by palaia itself (``sys.executable
fixture_stdio_server.py``) — the same interpreter/venv pytest runs in, so
``fastmcp`` is importable. It echoes back the value of ``FIXTURE_TOKEN``,
which is how ``test_stdio_upstream.py`` proves an env-var secret really
reached the child process rather than being dropped somewhere in the
transport.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

server: FastMCP = FastMCP(name="fixture-stdio-upstream")


@server.tool
def whoami() -> str:
    """Report which credential this process was started with."""
    return f"token={os.environ.get('FIXTURE_TOKEN', 'MISSING')}"


@server.tool
def add(a: int, b: int) -> int:
    """Add two numbers (a plain tool, no credential involved)."""
    return a + b


if __name__ == "__main__":
    server.run()
