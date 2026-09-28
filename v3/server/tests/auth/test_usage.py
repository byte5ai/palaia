"""Per-client memory use: lookups, saves and "saved before looking" (issue #524)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.server.auth import AccessToken

from palaia_hub.app import create_app
from palaia_hub.auth import usage as usage_module
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.usage import USAGE_DB_NAME, ClientUsageStore, classify
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService

DAY = 1_790_000_000.0  # 2026-09-21T13:33:20Z


def test_calls_are_classified_as_lookups_or_saves() -> None:
    assert classify("recall") == "lookup"
    assert classify("search") == "lookup"
    assert classify("capture") == "save"
    assert classify("write") == "save"
    assert classify("delete") is None
    assert classify("") is None


def test_counts_add_up_per_client_and_day(tmp_path: Path) -> None:
    store = ClientUsageStore(tmp_path)
    store.record("a", "lookup", now=DAY)
    store.record("a", "lookup", now=DAY)
    store.record("a", "save", now=DAY + 86400)
    store.record("b", "save", now=DAY)

    summary = {entry.client_id: entry for entry in store.summary(days=7, now=DAY + 86400)}

    assert (summary["a"].lookups, summary["a"].saves) == (2, 1)
    assert [(d.lookups, d.saves) for d in summary["a"].days] == [(2, 0), (0, 1)]
    assert (summary["b"].lookups, summary["b"].saves) == (0, 1)
    assert list(summary) == ["a", "b"]  # most active first
    store.close()


def test_a_session_that_saves_before_looking_anything_up_is_counted(tmp_path: Path) -> None:
    store = ClientUsageStore(tmp_path)
    store.record("a", "save", session_id="s1", now=DAY)
    store.record("a", "lookup", session_id="s1", now=DAY)
    store.record("a", "lookup", session_id="s2", now=DAY)
    store.record("a", "save", session_id="s2", now=DAY)

    (entry,) = store.summary(days=1, now=DAY)

    assert entry.sessions == 2
    assert entry.sessions_saved_first == 1
    store.close()


def test_the_counts_survive_a_restart_and_old_days_are_dropped(tmp_path: Path) -> None:
    store = ClientUsageStore(tmp_path)
    store.record("a", "lookup", now=DAY - 100 * 86400)
    store.record("a", "lookup", now=DAY)
    store.close()

    again = ClientUsageStore(tmp_path)
    (entry,) = again.summary(days=90, now=DAY)
    assert entry.lookups == 1  # the 100-day-old row was pruned
    assert (tmp_path / USAGE_DB_NAME).stat().st_mode & 0o777 == 0o600
    again.close()


def _gateway(store: ClientUsageStore) -> object:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    return build_gateway(config, {"work": FakeVaultService()}, client_usage=store)


@pytest.mark.anyio
async def test_the_gateway_counts_a_profiles_memory_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = AccessToken(token="t", client_id="tok1", scopes=[], subject="Claude Code")
    monkeypatch.setattr(usage_module, "get_access_token", lambda: token)
    store = ClientUsageStore(tmp_path)
    gateway = _gateway(store)

    async with Client(gateway.profile_servers["default"]) as client:  # type: ignore[attr-defined]
        await client.call_tool("work_memory_write", {"title": "A", "body": "x"})
        await client.call_tool("work_memory_search", {"query": "x"})
        await client.call_tool("work_memory_recall", {"query": "x"})
        await client.call_tool("memory_status", {})

    (entry,) = store.summary(days=1)
    assert entry.client_id == "tok1"
    assert (entry.lookups, entry.saves) == (2, 1)
    assert entry.sessions == 1
    assert entry.sessions_saved_first == 1
    store.close()


@pytest.mark.anyio
async def test_a_failed_call_is_not_counted(tmp_path: Path) -> None:
    store = ClientUsageStore(tmp_path)
    gateway = _gateway(store)

    async with Client(gateway.profile_servers["default"]) as client:  # type: ignore[attr-defined]
        await client.call_tool("work_memory_read", {"permalink": "nope"}, raise_on_error=False)

    assert store.summary(days=1) == []
    store.close()


def test_the_route_names_each_clients_token(tmp_path: Path) -> None:
    tokens = TokenStore(home=tmp_path)
    created = tokens.create("Claude Code", "default", [])
    store = ClientUsageStore(tmp_path)
    store.record(created.info.id, "save", session_id="s1")
    store.record("oauth-client", "lookup")
    app = create_app(HubConfig(), home=tmp_path, token_store=tokens, client_usage=store)

    with TestClient(app) as client:
        body = client.get("/api/auth/tokens/usage?days=7").json()

    by_id = {entry["client_id"]: entry for entry in body}
    assert by_id[created.info.id]["name"] == "Claude Code"
    assert by_id[created.info.id]["sessions_saved_first"] == 1
    assert by_id["oauth-client"]["name"] is None


def test_the_route_is_absent_on_a_hub_that_does_not_count(tmp_path: Path) -> None:
    app = create_app(HubConfig(), home=tmp_path, token_store=TokenStore(home=tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/auth/tokens/usage").status_code == 404
