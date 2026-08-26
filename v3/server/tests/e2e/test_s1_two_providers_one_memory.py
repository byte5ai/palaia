"""S1 "two providers, one memory" (SPEC-113).

Client A (a simulated Claude Code) writes a note; client B (a simulated
Codex, connecting through a different profile with a distinct MCP client
identity) finds and reads it — through the real gateway, over real
streamable HTTP, backed by the real vault engine (SPEC-102) over the golden
vault's ``work`` copy. Nothing here is faked: the only stand-in is the
"different token/profile" requirement, realized as two profile paths
mounting the *same* vault key (SPEC-105's actual multi-profile mechanism,
not an invented one) plus distinct MCP ``client_info`` per simulated client.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio


async def test_client_a_writes_client_b_finds_it_through_a_different_profile(
    golden_work_vault: Path, hub_factory: HubFactory
) -> None:
    hub = hub_factory(vault_dir=golden_work_vault, profiles=["claude-code", "codex"])

    async with SimulatedClient(
        hub.profile_url("claude-code"), client_name="claude-code", client_version="1.0.0"
    ) as client_a:
        write_result = await client_a.call_tool_ok(
            "work_memory_write",
            {
                "title": "S1 Round Trip",
                "body": "written by simulated client A (claude-code profile)",
            },
        )
        assert "S1 Round Trip" in write_result.text
        assert write_result.structured is not None
        permalink = write_result.structured["permalink"]

    # A brand new session, a different profile path, a different MCP
    # client identity — the "second provider" — never having talked to
    # client A directly.
    async with SimulatedClient(
        hub.profile_url("codex"), client_name="codex", client_version="1.0.0"
    ) as client_b:
        search_result = await client_b.call_tool_ok(
            "work_memory_search", {"query": "S1 Round Trip"}
        )
        assert "S1 Round Trip" in search_result.text

        read_result = await client_b.call_tool_ok("work_memory_read", {"permalink": permalink})
        assert "written by simulated client A" in read_result.text
