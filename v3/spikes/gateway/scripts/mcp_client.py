"""Scripted MCP client for the gateway spike, using the official python-sdk
(the `mcp` package) over streamable HTTP — the substitute Q5 client for this
sandbox (see FINDINGS.md, Q5, for why and what a human must additionally
verify with the real `claude` CLI/Claude Code app).

Usage:
    uv run python scripts/mcp_client.py <profile> <bearer_token> [tool] [args_json]

Examples:
    uv run python scripts/mcp_client.py full full-profile-secret-token
    uv run python scripts/mcp_client.py full full-profile-secret-token \
        local_memory_search '{"query": "onboarding"}'
    uv run python scripts/mcp_client.py memory-only memory-only-profile-secret-token
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8900"))


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)

    profile = sys.argv[1]
    token = sys.argv[2]
    tool_name = sys.argv[3] if len(sys.argv) > 3 else None
    tool_args = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}

    url = f"http://127.0.0.1:{GATEWAY_PORT}/mcp/{profile}/"
    headers = {"Authorization": f"Bearer {token}"}

    print(f"--- connecting to {url}")
    try:
        async with streamablehttp_client(url, headers=headers) as (
            read,
            write,
            _get_sid,
        ):
            async with ClientSession(read, write) as session:
                init_result = await session.initialize()
                print(
                    f"--- initialized: server={init_result.serverInfo.name} "
                    f"protocol={init_result.protocolVersion}"
                )

                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                print(
                    f"--- tool surface for profile '{profile}' ({len(names)}): {names}"
                )

                if tool_name:
                    print(f"--- calling {tool_name}({tool_args})")
                    result = await session.call_tool(tool_name, tool_args)
                    for block in result.content:
                        if hasattr(block, "text"):
                            print(f"--- result: {block.text}")
                        else:
                            print(f"--- result (non-text block): {block!r}")
                    if result.isError:
                        print("--- call reported isError=True")
    except* httpx.HTTPStatusError as eg:
        for exc in eg.exceptions:
            status = exc.response.status_code
            print(f"--- AUTH/HTTP REJECTED as expected? status={status} ({exc})")


if __name__ == "__main__":
    asyncio.run(main())
