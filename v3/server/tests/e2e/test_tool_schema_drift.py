"""Golden ``tools/list`` snapshot — SPEC-113 acceptance criterion: "harness
fails loudly on tool-schema drift".

Compares the memory tool family's live names, descriptions, input schemas
and behavior annotations against a committed snapshot
(``golden_tools_snapshot.json``). A deliberate tool-surface change (a
renamed parameter, a dropped annotation, a reworded description) MUST show
up here as a failing assertion with the exact diff, not as a silent
behavior change discovered later by some other SPEC's tests.

Regenerate the snapshot after an intentional change with::

    uv run python -c "
    import asyncio, json
    from fastmcp import Client
    from palaia_hub.gateway.config import VaultMountConfig
    from palaia_hub.gateway.fake_vault import FakeVaultService
    from palaia_hub.gateway.memory_tools import build_vault_server
    from simulator import tool_schema_snapshot

    async def main():
        server = build_vault_server(
            VaultMountConfig(key='work', name='work', purpose='A palaia memory vault.'),
            FakeVaultService(),
        )
        async with Client(server) as client:
            tools = await client.list_tools()
        print(json.dumps(tool_schema_snapshot(tools), indent=2, sort_keys=True))
    "
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client
from simulator import tool_schema_snapshot

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server

SNAPSHOT_PATH = Path(__file__).parent / "golden_tools_snapshot.json"


@pytest.mark.anyio
async def test_memory_tool_family_matches_golden_schema_snapshot() -> None:
    config = VaultMountConfig(key="work", name="work", purpose="A palaia memory vault.")
    server = build_vault_server(config, FakeVaultService())
    async with Client(server) as client:
        tools = await client.list_tools()

    live = tool_schema_snapshot(tools)
    golden = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert set(live) == set(golden), (
        f"tool surface drifted: added {set(live) - set(golden)}, "
        f"removed {set(golden) - set(live)}. If intentional, regenerate "
        f"{SNAPSHOT_PATH.name} (see this test module's docstring)."
    )
    for name in golden:
        assert live[name] == golden[name], (
            f"tool {name!r} schema/description/annotations drifted from the "
            f"golden snapshot. If intentional, regenerate {SNAPSHOT_PATH.name}."
        )
