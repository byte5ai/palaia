"""``create_app(gateway=...)`` actually mounts profiles, and the app still
starts fine with no gateway at all (the SPEC-101 skeleton's own behavior,
unchanged) — the "minimal additive registration" this SPEC adds to app.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService


def _build_test_gateway() -> object:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    return build_gateway(config, {"work": FakeVaultService()})


def test_app_with_no_gateway_behaves_exactly_as_before() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_app_with_gateway_mounts_the_profile_path_and_health_still_works() -> None:
    gateway = _build_test_gateway()
    app = create_app(HubConfig(), gateway=gateway)  # type: ignore[arg-type]

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        # A GET against the streamable-HTTP endpoint without the MCP
        # session headers is rejected, but the path must exist (i.e. be
        # routed to the mounted FastMCP app, not 404 from FastAPI itself).
        response = client.get("/mcp/default/")
        assert response.status_code != 404


def test_app_without_gateway_has_no_mcp_route() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)
    assert client.get("/mcp/default/").status_code == 404
