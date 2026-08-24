"""Golden ``tools/list`` snapshot for the stash tool family (SPEC-202) —
same drift protection as ``test_tool_schema_drift.py`` gives the memory
family.

Regenerate the snapshot after an intentional change with::

    uv run python -c "
    import asyncio, json, sys
    from fastmcp import Client
    sys.path.insert(0, 'server/tests/e2e')
    from simulator import tool_schema_snapshot
    from palaia_hub.gateway.stash_tools import build_stash_server
    from palaia_hub.stash.service import StashService
    from palaia_hub.stash.store import StashStore

    async def main():
        server = build_stash_server(StashService(StashStore(':memory:')))
        async with Client(server) as client:
            tools = await client.list_tools()
        print(json.dumps(tool_schema_snapshot(tools), indent=2, sort_keys=True))

    asyncio.run(main())
    " > server/tests/e2e/golden_stash_tools_snapshot.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client
from simulator import tool_schema_snapshot

from palaia_hub.gateway.stash_tools import build_stash_server
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore

SNAPSHOT_PATH = Path(__file__).parent / "golden_stash_tools_snapshot.json"


@pytest.mark.anyio
async def test_stash_tool_family_matches_golden_schema_snapshot() -> None:
    server = build_stash_server(StashService(StashStore(":memory:")))
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
