"""Stash browser MCP App acceptance tests (SPEC-405 deliverable #4).

Same in-memory :class:`fastmcp.Client` pattern as ``test_apps_hub_status.py``
(see that file's own docstring for why no test here drives a real HTTP
streamable session), against ``stash_browse`` — the tool
:mod:`palaia_hub.gateway.stash_tools` adds this SPEC, alongside the four
already there.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.apps.stash_browser_app import collect_stash_browse
from palaia_hub.gateway.stash_tools import build_stash_server
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore


def _service() -> StashService:
    return StashService(StashStore(":memory:"))


@pytest.mark.anyio
async def test_the_overview_never_carries_a_value() -> None:
    service = _service()
    await service.set("jobs", "job-1", {"secret-ish": "payload"})
    await service.set("jobs", "job-2", "another value")
    await service.set("rates", "user-a", 42)

    result = await collect_stash_browse(service)

    assert result.namespace == ""
    assert result.namespaces == {"jobs": 2, "rates": 1}
    assert result.total_entries == 3
    assert result.entries == []
    assert "payload" not in str(result.model_dump())


@pytest.mark.anyio
async def test_drilling_into_a_namespace_lists_entries_without_their_values() -> None:
    service = _service()
    await service.set("jobs", "job-1", {"secret-ish": "payload"}, ttl_seconds=3600)

    result = await collect_stash_browse(service, "jobs")

    assert result.namespace == "jobs"
    assert [e.key for e in result.entries] == ["job-1"]
    assert result.entries[0].expires_at is not None
    assert not hasattr(result.entries[0], "value")
    assert "payload" not in str(result.model_dump())


@pytest.mark.anyio
async def test_stash_browse_tool_carries_the_ui_resource_and_summarizes_in_text() -> None:
    service = _service()
    await service.set("jobs", "job-1", "x")
    server = build_stash_server(service)

    async with Client(server) as client:
        tools = await client.list_tools()
        (browse_tool,) = [t for t in tools if t.name == "stash_browse"]
        assert browse_tool.meta is not None
        assert browse_tool.meta["ui"]["resourceUri"] == "ui://palaia/stash_browser.html"

        overview = await client.call_tool("stash_browse", {})
        drill_down = await client.call_tool("stash_browse", {"namespace": "jobs"})
        resources = await client.list_resources()

    assert {str(r.uri) for r in resources} == {"ui://palaia/stash_browser.html"}
    assert "1 entries" in overview.content[0].text or "1 entr" in overview.content[0].text
    assert "job-1" in drill_down.content[0].text


def test_stash_browser_mount_reuses_the_existing_stash_mount() -> None:
    """The app is served from the *same* ``/mcp/stash`` mount as the rest
    of the stash family — no second mount to gate separately."""
    service = _service()
    app = create_app(HubConfig(), stash_service=service)
    with TestClient(app) as rest:
        assert rest.get("/mcp/stash").status_code == 406
