"""The ``/api/auth/tokens`` REST surface: create/list/revoke."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig


def _client(tmp_path: Path) -> TestClient:
    app = create_app(HubConfig(), token_store=TokenStore(home=tmp_path))
    return TestClient(app)


def test_create_returns_plaintext_once(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/auth/tokens",
        json={"name": "Codex on devbox", "profile": "default", "scopes": ["vault:work:read"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"].startswith("plt_")
    assert body["info"]["name"] == "Codex on devbox"
    assert "hash" not in body["info"]


def test_list_never_includes_plaintext_or_hash(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.post("/api/auth/tokens", json={"name": "a", "profile": "default", "scopes": []})

    response = client.get("/api/auth/tokens")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert "token" not in body[0]
    assert "hash" not in body[0]


def test_revoke_then_list_shows_revoked(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post(
        "/api/auth/tokens", json={"name": "a", "profile": "default", "scopes": []}
    ).json()

    response = client.delete(f"/api/auth/tokens/{created['info']['id']}")

    assert response.status_code == 200
    assert response.json()["revoked_at"] is not None


def test_revoke_unknown_id_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.delete("/api/auth/tokens/does-not-exist")

    assert response.status_code == 404


def test_invalid_scope_is_400(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/auth/tokens",
        json={"name": "a", "profile": "default", "scopes": ["not-a-scope"]},
    )

    assert response.status_code == 400


def test_router_absent_when_no_token_store_given() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/auth/tokens")

    assert response.status_code == 404
