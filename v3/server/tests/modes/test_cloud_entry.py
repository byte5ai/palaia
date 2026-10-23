"""The hub's own lock on the cloud entry (issues #566, #567)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig

CLOUD = {"x-palaia-entry": "cloud"}


def _client(home: Path, mode: str) -> TestClient:
    config = HubConfig(mode=mode, host="127.0.0.1", auth_enabled=True)  # type: ignore[arg-type]
    return TestClient(create_app(config, home=home))


@pytest.mark.parametrize("path", ["/api/info", "/api/health", "/api/mode", "/", "/assets/x.js"])
def test_admin_routes_and_the_dashboard_are_404_through_the_cloud_entry(
    tmp_path: Path, path: str
) -> None:
    response = _client(tmp_path, "cloud").get(path, headers=CLOUD)
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_the_ai_connection_passes_in_cloud_mode(tmp_path: Path) -> None:
    """No sign-in server in this test hub, so the route itself is absent — the
    answer comes from the hub's routing (FastAPI's ``detail``), not from the
    cloud-entry lock (``error: not_found``)."""
    response = _client(tmp_path, "cloud").get(
        "/.well-known/oauth-authorization-server", headers=CLOUD
    )
    assert response.status_code == 404
    assert "error" not in response.json()


def test_everything_is_closed_while_cloud_access_is_off(tmp_path: Path) -> None:
    for path in ("/mcp/default/", "/oauth/login", "/.well-known/oauth-authorization-server"):
        response = _client(tmp_path, "locked").get(path, headers=CLOUD)
        assert response.status_code == 403, path
        assert response.json()["error"] == "cloud_access_off"
        assert "turn on cloud access in the dashboard" in response.json()["error_description"]


def test_the_private_door_is_untouched(tmp_path: Path) -> None:
    client = _client(tmp_path, "locked")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/info").status_code == 200
