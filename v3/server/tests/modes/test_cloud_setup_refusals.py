"""Issue #561: transitions the hub could not start from are refused up front,
and a sign-in server with nothing to grant no longer takes the hub down."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.cli import _maybe_oauth_server
from palaia_hub.config import HubConfig, load_config
from palaia_hub.startup import PROBLEMS
from palaia_hub.vault import VaultRegistry


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


def test_a_sign_in_server_with_nothing_to_grant_is_skipped_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hub whose config.yaml turns sign-in on before any memory exists
    starts without the sign-in server and says why, instead of exiting into
    a restart loop that takes the dashboard down with it."""
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "oauth:\n  enabled: true\n  issuer: https://hub.example.test\n", encoding="utf-8"
    )
    PROBLEMS.clear()
    try:
        assert _maybe_oauth_server(load_config(home=tmp_path)) is None
        assert PROBLEMS and "has no memory yet" in PROBLEMS[0]
    finally:
        PROBLEMS.clear()
