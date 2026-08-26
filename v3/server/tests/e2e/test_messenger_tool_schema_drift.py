"""Golden ``tools/list`` snapshot for the messenger tool family (SPEC-403)
— same drift protection as ``test_directory_tool_schema_drift.py`` gives the
session directory. The envelope is a protocol two providers agree on, so its
tool surface changing silently is exactly the failure this catches.

Regenerate the snapshot after an intentional change with::

    uv run python -c "
    import asyncio, json, sys
    from fastmcp import Client
    sys.path.insert(0, 'server/tests/e2e')
    from simulator import tool_schema_snapshot
    from palaia_hub.gateway.messenger_tools import build_messenger_server
    from palaia_hub.directory.service import DirectoryService
    from palaia_hub.directory.store import DirectoryStore
    from palaia_hub.messenger.service import MessengerService
    from palaia_hub.messenger.store import MessengerStore

    async def main():
        directory = DirectoryService(DirectoryStore(':memory:'))
        service = MessengerService(MessengerStore(':memory:'), directory)
        server = build_messenger_server(service)
        async with Client(server) as client:
            tools = await client.list_tools()
        print(json.dumps(tool_schema_snapshot(tools), indent=2, sort_keys=True))

    asyncio.run(main())
    " > server/tests/e2e/golden_messenger_tools_snapshot.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastmcp import Client
from simulator import tool_schema_snapshot

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.messenger_tools import build_messenger_server
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore

SNAPSHOT_PATH = Path(__file__).parent / "golden_messenger_tools_snapshot.json"


@pytest.mark.anyio
async def test_messenger_tool_family_matches_golden_schema_snapshot() -> None:
    directory = DirectoryService(DirectoryStore(":memory:"))
    service = MessengerService(MessengerStore(":memory:"), directory)
    server = build_messenger_server(service)
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
