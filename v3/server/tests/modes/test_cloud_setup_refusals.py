"""Issue #561: transitions the hub could not start from are refused up front,
and a sign-in server with nothing to grant no longer takes the hub down — nor
is it left out, which would leave the admin API without its sign-in."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from palaia_hub.admin_session import sign_in_configured, sign_in_required
from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.cli import _maybe_oauth_server
from palaia_hub.config import HubConfig, load_config
from palaia_hub.oauth import OAuthStore, set_owner_password
from palaia_hub.serve import build_production_app
from palaia_hub.startup import PROBLEMS
from palaia_hub.vault import VaultRegistry


@pytest.fixture(autouse=True)
def _no_leftover_problems() -> Iterator[None]:
    """Start-up problems are process-wide; a hub started here must not leave
    its own behind for the next test to read."""
    PROBLEMS.clear()
    yield
    PROBLEMS.clear()


def _client(home: Path) -> TestClient:
    return TestClient(create_app(HubConfig(), home=home, vault_registry=VaultRegistry(home)))


def test_turning_sign_in_on_before_the_first_memory_is_refused(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/api/mode", json={"oauth_enabled": True, "oauth_issuer": "http://100.64.0.1:8420"}
    )
    assert response.status_code == 400
    assert "Create your first memory before turning on sign-in" in response.json()["detail"]
    # Nothing was written that the next start would trip over.
    assert load_config(tmp_path).oauth.enabled is False


def test_turning_sign_in_on_after_the_first_memory_is_accepted(tmp_path: Path) -> None:
    asyncio.run(VaultRegistry(tmp_path).create("work", path=tmp_path / "vaults" / "work"))
    response = _client(tmp_path).post(
        "/api/mode", json={"oauth_enabled": True, "oauth_issuer": "http://100.64.0.1:8420"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["restart_required"] is True


def test_cloud_mode_refuses_a_plain_http_sign_in_address(tmp_path: Path) -> None:
    """The dashboard used to send its own private http origin as the issuer."""
    asyncio.run(VaultRegistry(tmp_path).create("work", path=tmp_path / "vaults" / "work"))
    response = _client(tmp_path).post(
        "/api/mode",
        json={
            "mode": "cloud",
            "host": "127.0.0.1",
            "oauth_enabled": True,
            "oauth_issuer": "http://100.64.0.1:8420",
        },
    )
    assert response.status_code == 400
    assert "must be an https:// URL" in response.json()["detail"]


def test_cloud_mode_with_the_public_https_address_is_accepted(tmp_path: Path) -> None:
    asyncio.run(VaultRegistry(tmp_path).create("work", path=tmp_path / "vaults" / "work"))
    url = "https://palaia-hub.tail1234.ts.net"
    response = _client(tmp_path).post(
        "/api/mode",
        json={
            "mode": "cloud",
            "host": "127.0.0.1",
            "oauth_enabled": True,
            "oauth_issuer": url,
            "public_url": url,
            "tunnel": "tailscale",
        },
    )
    assert response.status_code == 200, response.text
    config = load_config(tmp_path)
    assert (config.mode, config.oauth.issuer, config.exposure.public_url) == ("cloud", url, url)


def test_a_sign_in_server_with_nothing_to_grant_still_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hub whose config.yaml turns sign-in on before any memory exists
    starts its sign-in server anyway — with nothing for AI apps to be granted
    yet, and says so — instead of exiting into a restart loop (#561) or
    starting without the owner's sign-in at all."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "oauth:\n  enabled: true\n  issuer: https://hub.example.test\n", encoding="utf-8"
    )
    server = _maybe_oauth_server(load_config(home=tmp_path))
    assert server is not None
    assert server.grantable_scopes() == {}
    server.store.close()
    assert PROBLEMS and "has no memory yet" in PROBLEMS[0]


def test_open_mode_with_no_memory_still_requires_the_owner_to_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A public hub whose last memory is gone (or not created yet) used to
    start with no sign-in server — and therefore with the admin API open to
    the internet. The owner's sign-in never depends on memories existing."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "mode: open\nhost: 0.0.0.0\nauth_enabled: true\n"
        "oauth:\n  enabled: true\n  issuer: https://hub.example.test\n",
        encoding="utf-8",
    )
    store = OAuthStore(tmp_path)
    store.open()
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=1_800_000_000)
    store.close()
    config = load_config(home=tmp_path)
    server = _maybe_oauth_server(config)
    assert server is not None
    try:
        app = create_app(
            config,
            home=tmp_path,
            oauth_server=server,
            vault_registry=VaultRegistry(tmp_path),
            token_store=TokenStore(home=tmp_path),
        )
        with TestClient(app) as client:
            assert client.get("/api/mode").status_code == 401
            assert client.post("/api/mode", json={"mode": "locked"}).status_code == 401
            assert client.get("/api/info").json()["sign_in"]["required"] is True
    finally:
        server.store.close()


@pytest.mark.anyio
async def test_a_memory_created_after_a_sign_in_server_with_nothing_to_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sign-in server now starts with no profile at all, so the first
    memory's profile is one it has never heard of: creating it must work, and
    the new AI connection must still ask for a token."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "oauth:\n  enabled: true\n  issuer: https://hub.example.test\n", encoding="utf-8"
    )
    config = load_config(home=tmp_path)
    server = _maybe_oauth_server(config)
    assert server is not None
    production = await build_production_app(config, home=tmp_path, oauth_server=server)
    app = production.app
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://hub.example.test"
            ) as http:
                created = await http.post("/api/vaults", json={"key": "work"})
                assert created.status_code == 200, created.text
                anonymous = await http.post("/mcp/default/", json={})
                assert anonymous.status_code == 401
    finally:
        await production.dynamic_gateway.aclose()
        if production.stash_store is not None:
            production.stash_store.close()
        for index in production.indexes.values():
            await index.close()
        server.store.close()


def test_the_dashboard_sign_in_requirement_can_be_set_and_needs_a_restart(tmp_path: Path) -> None:
    """Issue #571: `dashboard.require_sign_in` had no control, so backups stayed
    unreachable in the default private setup with no way to fix it."""
    client = _client(tmp_path)
    response = client.post("/api/mode", json={"dashboard_require_sign_in": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dashboard_require_sign_in"] is True
    assert body["restart_required"] is True
    assert load_config(tmp_path).dashboard.require_sign_in is True


def test_switching_a_cloud_hub_to_private_keeps_its_dashboard_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #588: the change Settings › Switch to Private sends. Private alone
    turns the dashboard's sign-in off; kept, with the sign-in server moved to
    the private address (the public one answers nothing in Private), the hub
    accepts it, still starts its sign-in server and still asks for the owner's
    password — and the public address stays saved for switching back."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    asyncio.run(VaultRegistry(tmp_path).create("work", path=tmp_path / "vaults" / "work"))
    store = OAuthStore(tmp_path)
    store.open()
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=1_800_000_000)
    store.close()
    public = "https://palaia-hub.tail1234.ts.net"
    private = "http://100.64.0.1:8420"
    client = _client(tmp_path)
    cloud = client.post(
        "/api/mode",
        json={
            "mode": "cloud",
            "host": "127.0.0.1",
            "oauth_enabled": True,
            "oauth_issuer": public,
            "public_url": public,
        },
    )
    assert cloud.status_code == 200, cloud.text

    response = client.post(
        "/api/mode",
        json={"mode": "locked", "dashboard_require_sign_in": True, "oauth_issuer": private},
    )

    assert response.status_code == 200, response.text
    config = load_config(tmp_path)
    assert (config.mode, config.oauth.issuer, config.exposure.public_url) == (
        "locked",
        private,
        public,
    )
    assert sign_in_required(config)
    assert sign_in_configured(config, tmp_path)
    server = _maybe_oauth_server(config)
    assert server is not None
    try:
        assert server.issuer == private
    finally:
        server.store.close()
