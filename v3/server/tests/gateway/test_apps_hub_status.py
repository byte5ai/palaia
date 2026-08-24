"""Hub status MCP App acceptance tests (SPEC-208 deliverable #2).

The tool-protocol tests below drive :func:`build_hub_status_server`
in-memory via :class:`fastmcp.Client` — this codebase's usual way of
testing a tool family (see ``test_memory_tools.py``, ``test_app_stash.py``'s
sibling ``build_stash_server``) — rather than through a real HTTP
round-trip against the ``/mcp/hub`` mount: no test in this repo drives an
MCP session through a bare ``fastapi.testclient.TestClient`` (the
streamable-HTTP session-ID handshake needs a real transport; this
codebase's e2e tests spin up an actual uvicorn subprocess for that, which
is out of proportion for asserting "the mount exists"). The one HTTP-level
test here only checks that the mount is present/absent, not the protocol
riding on it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.auth import TokenStore
from palaia_hub.config import HubConfig
from palaia_hub.gateway.apps.hub_status_app import (
    HubStatusDeps,
    build_hub_status_server,
    collect_hub_status,
)
from palaia_hub.vault import VaultRegistry


@pytest.mark.anyio
async def test_collect_hub_status_reports_vaults_and_clients(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "home")
    await registry.create("work", tmp_path / "work", purpose="Team knowledge.")

    tokens = TokenStore(tmp_path / "auth")
    created = tokens.create("claude-code", "default", ["vault:work:read"])
    tokens.verify(created.token)

    deps = HubStatusDeps(
        vault_registry=registry,
        indexes=None,
        token_store=tokens,
        mode="locked",
        start_time=0.0,
    )
    status = await collect_hub_status(deps)

    assert status.mode == "locked"
    assert [v.key for v in status.vaults] == ["work"]
    assert status.vaults[0].purpose == "Team knowledge."
    assert [c.name for c in status.clients] == ["claude-code"]
    assert status.clients[0].last_used_at is not None


@pytest.mark.anyio
async def test_collect_hub_status_omits_revoked_tokens(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "home")
    tokens = TokenStore(tmp_path / "auth")
    created = tokens.create("old-client", "default", [])
    tokens.revoke(created.info.id)

    deps = HubStatusDeps(
        vault_registry=registry, indexes=None, token_store=tokens, mode="locked", start_time=0.0
    )
    status = await collect_hub_status(deps)
    assert status.clients == []


@pytest.mark.anyio
async def test_hub_status_tool_is_reachable_and_carries_the_ui_resource(
    tmp_path: Path,
) -> None:
    registry = VaultRegistry(tmp_path / "home")
    await registry.create("work", tmp_path / "work")
    deps = HubStatusDeps(
        vault_registry=registry, indexes=None, token_store=None, mode="locked", start_time=0.0
    )
    server = build_hub_status_server(deps)

    async with Client(server) as client:
        tools = await client.list_tools()
        (hub_status_tool,) = [t for t in tools if t.name == "hub_status"]
        assert hub_status_tool.meta is not None
        assert hub_status_tool.meta["ui"]["resourceUri"] == "ui://palaia/hub_status.html"

        result = await client.call_tool("hub_status", {})
        resources = await client.list_resources()

    assert {str(r.uri) for r in resources} == {"ui://palaia/hub_status.html"}
    payload = result.structured_content
    assert [v["key"] for v in payload["vaults"]] == ["work"]
    # Plain-text fallback (deliverable #5): a usable summary with no app host.
    assert "1 vault" in result.content[0].text


def test_hub_status_mount_present_only_with_a_vault_registry(tmp_path: Path) -> None:
    without_registry = create_app(HubConfig())
    with TestClient(without_registry) as rest:
        assert rest.get("/mcp/hub").status_code == 404

    registry = VaultRegistry(tmp_path / "home")
    with_registry = create_app(HubConfig(), vault_registry=registry)
    with TestClient(with_registry) as rest:
        # 406 (not 404): a real MCP streamable-HTTP endpoint refusing a GET
        # that lacks `Accept: text/event-stream` — proof the mount exists,
        # distinct from "no such route" (see the module docstring for why a
        # full JSON-RPC round trip through this HTTP layer is not attempted
        # here — the in-memory Client tests above already drive the real
        # protocol against the same server this mount wraps).
        assert rest.get("/mcp/hub").status_code == 406
