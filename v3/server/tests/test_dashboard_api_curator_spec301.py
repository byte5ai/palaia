"""SPEC-301 deliverable #4, at the dashboard-router layer: the wizard's
``POST /api/vaults`` handler actually wires a runtime-created vault into
the curator (not just the gateway) when one is running.

``tests/curator/test_runtime_join.py`` proves the underlying mechanism end
to end (a scripted curation session actually curates the new vault); this
file proves :mod:`palaia_hub.dashboard_api` actually calls it, through the
same ``create_app``/``build_dashboard_router`` wiring production uses.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.curator.middleware import CuratorScopeMiddleware
from palaia_hub.curator.profile import CURATOR_PROFILE_PATH
from palaia_hub.curator.wiring import build_curator
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.vault import VaultEngine, VaultRegistry


def test_vault_created_via_the_wizard_joins_the_curator_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    registry = VaultRegistry(home)

    vault_root = home / "vaults" / "work"
    vault_root.parent.mkdir(parents=True, exist_ok=True)
    engine = VaultEngine(vault_root, name="work")
    # `.open()` does no loop-bound background work of its own — safe to run
    # to completion on a throwaway loop, unlike `DynamicGateway.start()`
    # below, which must run on the same loop `TestClient` drives.
    asyncio.run(engine.open(purpose="Work vault.", create=True))

    mount = VaultMountConfig(key="work", name="work", purpose="Work vault.")
    hub_config = HubConfig(curator={"enabled": True})
    curator = build_curator(
        hub_config, {"work": engine}, [mount], home=home, with_stash=False
    )
    gateway = DynamicGateway(
        GatewayConfig(
            vaults=[mount],
            profiles=[
                ProfileConfig(path="default", vaults=["work"]),
                ProfileConfig(path=CURATOR_PROFILE_PATH, vaults=["work"]),
            ],
        ),
        {"work": FakeVaultService()},
        profile_middleware=curator.profile_middleware,
    )
    # Not started here — `create_app`'s own lifespan (run inside
    # `TestClient`'s `with` block below) starts it on the loop that will
    # actually serve requests, which is what its background lifecycle task
    # must be bound to (see `DynamicGateway`'s own docstring).

    app = create_app(
        hub_config,
        vault_registry=registry,
        dynamic_gateway=gateway,
        curator_wiring=curator,  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        response = client.post("/api/vaults", json={"key": "personal", "purpose": "Personal."})
        assert response.status_code == 200

        # The dashboard's create_vault handler wired the curator too —
        # SPEC-206's documented gap, closed.
        assert "personal" in curator.runners  # type: ignore[attr-defined]

        mcp_response = client.get(f"/mcp/{CURATOR_PROFILE_PATH}/")
        assert mcp_response.status_code != 404

    middleware = curator.profile_middleware[CURATOR_PROFILE_PATH][0]  # type: ignore[index]
    assert isinstance(middleware, CuratorScopeMiddleware)
    # The guard's tool-action map recognizes the runtime-added vault's
    # tools now — previously unmapped and fail-closed until a restart.
    assert middleware.action_for("personal_memory_write") == "write"
