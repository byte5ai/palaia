"""SPEC-210: the dashboard's ``index_status`` route, and ``create_vault``
opening a real index + mounting into a running :class:`DynamicGateway`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.config import GatewayConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.index import VaultIndex
from palaia_hub.vault import VaultRegistry


def _client(
    tmp_path: Path,
    *,
    with_indexes: bool = True,
    with_dynamic_gateway: bool = True,
) -> TestClient:
    registry = VaultRegistry(tmp_path / "home")
    indexes: dict[str, VaultIndex] = {} if with_indexes else None  # type: ignore[assignment]
    dynamic_gateway = (
        DynamicGateway(GatewayConfig(), {}) if with_dynamic_gateway else None
    )
    app = create_app(
        HubConfig(),
        vault_registry=registry,
        indexes=indexes,
        dynamic_gateway=dynamic_gateway,
    )
    return TestClient(app)


def test_index_status_absent_without_indexes_param(tmp_path: Path) -> None:
    with _client(tmp_path, with_indexes=False) as client:
        client.post("/api/vaults", json={"key": "work"})
        response = client.get("/api/vaults/work/index_status")
    assert response.status_code == 404


def test_index_status_after_create_vault(tmp_path: Path) -> None:
    with _client(tmp_path, with_dynamic_gateway=False) as client:
        created = client.post("/api/vaults", json={"key": "work", "template": True})
        assert created.status_code == 200

        response = client.get("/api/vaults/work/index_status")
        assert response.status_code == 200
        body = response.json()
        assert body["vault"] == "work"
        # The starter template's two notes plus the manifest.
        assert body["notes"] == 3
        assert "embed_summary" in body
        assert body["embed_progress_percent"] >= 0


def test_index_status_404_for_unknown_vault(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/vaults/nope/index_status")
    assert response.status_code == 404


def test_create_vault_mounts_it_on_the_dynamic_gateway(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/vaults", json={"key": "work", "purpose": "Work stuff."})
        assert response.status_code == 200

        mcp_response = client.get("/mcp/default/")
        # Mounted (not 404) — SPEC-210's whole point: reachable with no
        # restart between the two requests above.
        assert mcp_response.status_code != 404


def test_search_after_create_vault_runs_through_the_real_index(tmp_path: Path) -> None:
    with _client(tmp_path, with_dynamic_gateway=False) as client:
        client.post("/api/vaults", json={"key": "work", "template": True})

        response = client.get("/api/vaults/work/search", params={"q": "starter note"})
        assert response.status_code == 200
        hits = response.json()
        assert any("Welcome" in hit["title"] for hit in hits)
