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
        {
            "path": "default",
            "label": None,
            "vaults": ["work"],
            "stash": False,
            "directory": False,
            # SPEC-403: the messenger opt-in, off until a profile asks for it.
            "messenger": False,
            "hidden_tools": [],
            "semantic_routing": False,
            "tool_count": 15,
            # SPEC-302: external servers this profile mounts — empty until
            # one is connected, which is every hub until someone does.
            "upstreams": [],
            "managed": False,
        }
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


def test_update_profile_changes_directory_flag_live(tmp_path: Path) -> None:
    gateway = _gateway()
    with _client(tmp_path, gateway=gateway) as client:
        response = client.patch("/api/gateway/profiles/default", json={"directory": True})
        assert response.status_code == 200
        body = response.json()
        assert body["directory"] is True
        assert body["stash"] is False  # omitted field keeps its value


def test_create_profile_with_directory_true_is_persisted(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles",
            json={"path": "personal", "vaults": ["work"], "directory": True},
        )
        assert response.status_code == 200
        assert response.json()["directory"] is True

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    profiles = on_disk["gateway"]["profiles"]
    assert next(p for p in profiles if p["path"] == "personal")["directory"] is True


def test_update_profile_changes_messenger_flag_live(tmp_path: Path) -> None:
    """SPEC-403: the ``messenger`` opt-in threads the same path as
    ``stash``/``directory`` — REST → live gateway → config.yaml."""
    gateway = _gateway()
    with _client(tmp_path, gateway=gateway) as client:
        response = client.patch("/api/gateway/profiles/default", json={"messenger": True})
        assert response.status_code == 200
        body = response.json()
        assert body["messenger"] is True
        assert body["directory"] is False  # omitted field keeps its value


def test_create_profile_with_messenger_true_is_persisted(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles",
            json={"path": "peers", "vaults": ["work"], "messenger": True},
        )
        assert response.status_code == 200
        assert response.json()["messenger"] is True

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    profiles = on_disk["gateway"]["profiles"]
    assert next(p for p in profiles if p["path"] == "peers")["messenger"] is True


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


def test_create_profile_with_hidden_tools_hides_them_live_and_persists(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles",
            json={
                "path": "restricted",
                "vaults": ["work"],
                "hidden_tools": ["work_memory_delete"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["hidden_tools"] == ["work_memory_delete"]
        assert body["tool_count"] == 14  # 15 memory-family tools, one hidden

        tools = client.get("/api/gateway/profiles/restricted/tools").json()
        hidden = {t["name"] for t in tools if t["hidden"]}
        assert hidden == {"work_memory_delete"}

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    restricted = next(
        p for p in on_disk["gateway"]["profiles"] if p["path"] == "restricted"
    )
    assert restricted["hidden_tools"] == ["work_memory_delete"]


def test_semantic_routing_profile_reports_two_live_tools(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.post(
            "/api/gateway/profiles",
            json={"path": "routed", "vaults": ["work"], "semantic_routing": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["semantic_routing"] is True
        assert body["tool_count"] == 2

        tools = {t["name"] for t in client.get("/api/gateway/profiles/routed/tools").json()}
        assert tools == {"find_tool", "invoke_tool"}


def test_list_profile_tools_for_unknown_profile_is_404(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.get("/api/gateway/profiles/nope/tools")
    assert response.status_code == 404


def test_list_and_update_vault_identity_round_trips_and_applies_live(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        listing = client.get("/api/gateway/vaults").json()
        assert listing == [
            {
                "key": "work",
                "name": "work",
                "purpose": "Work vault.",
                "tool_renames": {},
                "namespace": "work_memory",
                "sanitized": [],
            }
        ]

        response = client.patch(
            "/api/gateway/vaults/work",
            json={"name": "Work Notes", "tool_renames": {"search": "find"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Work Notes"
        assert body["tool_renames"] == {"search": "find"}
        assert body["sanitized"] == []

        mcp_tools = client.get("/api/gateway/profiles/default/tools").json()
        names = {t["name"] for t in mcp_tools}
        assert "Work_Notes_memory_find" in names
        assert "Work_Notes_memory_search" not in names

    on_disk = yaml.safe_load((config_file_path(tmp_path)).read_text(encoding="utf-8"))
    on_disk_vault = on_disk["gateway"]["vaults"][0]
    assert on_disk_vault["key"] == "work"
    assert on_disk_vault["name"] == "Work Notes"
    assert on_disk_vault["tool_renames"] == {"search": "find"}


def test_update_vault_identity_sanitizes_invalid_rename_and_reports_it(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.patch(
            "/api/gateway/vaults/work",
            json={"tool_renames": {"search": "find notes!"}},
        )
        assert response.status_code == 200
        body = response.json()
        # The raw value round-trips as typed...
        assert body["tool_renames"] == {"search": "find notes!"}
        # ...but the response says exactly what will be sanitized to what.
        assert body["sanitized"] == [
            {"action": "search", "requested": "find notes!", "applied": "find_notes"}
        ]

        mcp_tools = {t["name"] for t in client.get("/api/gateway/profiles/default/tools").json()}
        assert "work_memory_find_notes" in mcp_tools


def test_update_vault_identity_unknown_key_is_404(tmp_path: Path) -> None:
    with _client(tmp_path, gateway=_gateway()) as client:
        response = client.patch("/api/gateway/vaults/ghost", json={"name": "x"})
    assert response.status_code == 404


def test_delete_default_profile_is_refused_server_side(tmp_path: Path) -> None:
    """SPEC-305 deliverable #5's guardrail is not UI-only: the API itself
    refuses to delete the default profile."""
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    with _client(tmp_path, gateway=gateway) as client:
        response = client.delete("/api/gateway/profiles/default")
        assert response.status_code == 400
        assert "cannot be deleted" in response.json()["detail"]

        listing = client.get("/api/gateway/profiles").json()
        assert {p["path"] for p in listing} == {"default"}
