"""Marketplace MCP App acceptance tests (SPEC-304 deliverable #5).

Same in-memory :class:`fastmcp.Client` pattern as
``test_apps_hub_status.py`` (see that file's own docstring for why no test
here drives a real HTTP streamable session) — plus the one thing unique to
this app: proving "install itself always deep-links to the dashboard...
the app never performs the install" by inspecting the page's own script
rather than a browser.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.apps.market_app import (
    _SCRIPT_JS,
    MarketAppDeps,
    build_market_server,
    collect_market_browse,
    render_marketplace_html,
)
from palaia_hub.market.curated import CuratedIndexClient
from palaia_hub.market.manual import ManualEntryStore
from palaia_hub.market.service import MarketService
from palaia_hub.registry.client import RegistryClient


def _empty_registry_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"servers": []})


def _offline_curated_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline in this test")


def _market_service(tmp_path: Path) -> MarketService:
    registry_client = RegistryClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_empty_registry_handler)),
        cache_dir=tmp_path / "registry_cache",
    )
    curated_client = CuratedIndexClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_offline_curated_handler)),
        last_good_path=tmp_path / "last_good.json",
    )
    manual_store = ManualEntryStore(tmp_path / "manual.sqlite3")
    return MarketService(
        registry_client=registry_client, curated_client=curated_client, manual_store=manual_store
    )


@pytest.mark.anyio
async def test_collect_market_browse_reads_the_starter_index(tmp_path: Path) -> None:
    deps = MarketAppDeps(market_service=_market_service(tmp_path), dashboard_url=None)

    result = await collect_market_browse(deps)

    assert {e.id for e in result.entries} >= {"palaia.fetch", "palaia.filesystem"}
    assert result.dashboard_url is None


@pytest.mark.anyio
async def test_market_tool_is_reachable_and_carries_the_ui_resource(tmp_path: Path) -> None:
    deps = MarketAppDeps(
        market_service=_market_service(tmp_path), dashboard_url="https://hub.example.com"
    )
    server = build_market_server(deps)

    async with Client(server) as client:
        tools = await client.list_tools()
        (browse_tool,) = [t for t in tools if t.name == "browse_marketplace"]
        assert browse_tool.meta is not None
        assert browse_tool.meta["ui"]["resourceUri"] == "ui://palaia/marketplace.html"

        result = await client.call_tool("browse_marketplace", {})
        resources = await client.list_resources()

    assert {str(r.uri) for r in resources} == {"ui://palaia/marketplace.html"}
    payload = result.structured_content
    assert payload["dashboard_url"] == "https://hub.example.com"
    # Plain-text fallback (SPEC-304 deliverable #5: "plain-text fallback
    # lists top results") — a usable summary with no app host at all.
    assert "Browse results" in result.content[0].text


@pytest.mark.anyio
async def test_a_search_query_narrows_the_plain_text_summary(tmp_path: Path) -> None:
    deps = MarketAppDeps(market_service=_market_service(tmp_path), dashboard_url=None)
    server = build_market_server(deps)

    async with Client(server) as client:
        result = await client.call_tool("browse_marketplace", {"query": "filesystem"})

    assert result.structured_content["query"] == "filesystem"
    assert [e["id"] for e in result.structured_content["entries"]] == ["palaia.filesystem"]


def test_the_page_never_calls_a_server_tool_to_install() -> None:
    """SPEC-304 deliverable #5: "install itself always deep-links to the
    dashboard consent screen — the app never performs the install".
    Asserted against the page's own script, since no browser drives it
    here (see the module docstring)."""
    # The vendored bridge SDK (embedded in every app's page) defines
    # `callServerTool` as a method every app *could* use — checking the
    # whole rendered page would always find that definition. What matters
    # is that *this app's own* script (`_SCRIPT_JS`, this page's only
    # page-specific logic) never invokes it at all.
    assert "callServerTool" not in _SCRIPT_JS
    # The deep link is a plain anchor, opened in a new tab/window — never a
    # fetch/XHR (which the app's strict CSP would refuse anyway).
    assert 'target="_blank"' in _SCRIPT_JS
    assert "installHref" in _SCRIPT_JS
    assert render_marketplace_html()  # still renders as one full page


def test_market_mount_present_only_with_a_market_service(tmp_path: Path) -> None:
    without_service = create_app(HubConfig())
    with TestClient(without_service) as rest:
        assert rest.get("/mcp/market").status_code == 404

    with_service = create_app(HubConfig(), market_service=_market_service(tmp_path))
    with TestClient(with_service) as rest:
        # 406, not 404 — same "the mount exists" proof
        # test_apps_hub_status.py's own mount test uses (see that file's
        # docstring for why no full JSON-RPC round trip is attempted here).
        assert rest.get("/mcp/market").status_code == 406
