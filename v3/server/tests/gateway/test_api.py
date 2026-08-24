"""Integration tests for the runtime profile-editor REST surface
(SPEC-301 deliverable #2): ``/api/gateway/profiles``."""

from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig, config_file_path
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService


def _client(tmp_path: Path, *, gateway: DynamicGateway) -> TestClient:
    app = create_app(HubConfig(), dynamic_gateway=gateway, home=tmp_path)
    return TestClient(app)


def _gateway() -> DynamicGateway:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    return DynamicGateway(config, {"work": FakeVaultService()})


def test_list_profiles_reports_the_live_shape(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.get("/api/gateway/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {"path": "default", "label": None, "vaults": ["work"], "stash": False, "managed": False}
    ]


def test_create_profile_is_reachable_immediately_and_persisted(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles",
            json={"path": "personal", "label": "Personal", "vaults": ["work"], "stash": False},
        )
        assert response.status_code == 200
        assert response.json()["label"] == "Personal"

        mcp_response = client.get("/mcp/personal/")
        assert mcp_response.status_code != 404

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    profiles = on_disk["gateway"]["profiles"]
    assert any(p["path"] == "personal" for p in profiles)


def test_create_profile_with_unknown_vault_is_refused(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles", json={"path": "personal", "vaults": ["ghost"]}
        )
    assert response.status_code == 400


def test_create_profile_with_a_duplicate_path_is_refused(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles", json={"path": "default", "vaults": ["work"]}
        )
    assert response.status_code == 400


def test_update_profile_changes_vaults_and_stash_live(tmp_path: Path) -> None:
    gateway = _gateway()
    with _client(tmp_path, gateway=gateway) as client:
        response = client.patch(
            "/api/gateway/profiles/default", json={"stash": True, "label": "Everything"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["stash"] is True
        assert body["label"] == "Everything"
        assert body["vaults"] == ["work"]  # omitted field keeps its value


def test_update_profile_cannot_touch_the_curator_profile(tmp_path: Path) -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="curator", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    with _client(tmp_path, gateway=gateway) as client:
        response = client.patch("/api/gateway/profiles/curator", json={"stash": True})
    assert response.status_code == 400


def test_delete_profile_unmounts_it_and_persists(tmp_path: Path) -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[
            ProfileConfig(path="default", vaults=["work"]),
            ProfileConfig(path="personal", vaults=["work"]),
        ],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    with _client(tmp_path, gateway=gateway) as client:
        response = client.delete("/api/gateway/profiles/personal")
        assert response.status_code == 204

        mcp_response = client.get("/mcp/personal/")
        assert mcp_response.status_code == 404

        listing = client.get("/api/gateway/profiles").json()
        assert {p["path"] for p in listing} == {"default"}

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    assert {p["path"] for p in on_disk["gateway"]["profiles"]} == {"default"}


def test_delete_unknown_profile_is_404(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.delete("/api/gateway/profiles/nope")
    assert response.status_code == 404
