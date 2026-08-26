"""``GET /api/funnel/status`` (SPEC-504 deliverable #3), mounted the same
"always on, like /api/health" way every hub gets it — see
``palaia_hub.app``'s own wiring.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.vault import EventBus as VaultEventBus
from palaia_hub.vault import VaultRegistry


def test_funnel_status_is_mounted_on_every_hub(tmp_path: Path) -> None:
    # An isolated `home`: without one, this reads from (and pollutes)
    # whatever this machine's real palaia_home() already has on disk from
    # some other process or test run entirely — the same "pass tmp_path
    # when a test's assertions depend on exact state" convention every
    # other hub-home-touching test in this suite already follows.
    #
    # `TestClient(app).get(...)` used outside a `with` block never runs
    # the app's lifespan (that is where `hub.started` fires — see
    # `palaia_hub.app`), so every field genuinely starts out unset here,
    # not just the three wizard-step ones.
    app = create_app(HubConfig(), home=tmp_path)
    client = TestClient(app)

    response = client.get("/api/funnel/status")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "hub_started_at": None,
        "vault_created_at": None,
        "client_connected_at": None,
        "first_memory_at": None,
        "time_to_first_memory_seconds": None,
        "time_to_first_memory_display": None,
    }


def test_vault_created_via_the_dashboard_router_shows_up_in_funnel_status() -> None:
    # A registry with a real vault.events.EventBus so create_app() bridges
    # it onto the public bus (see palaia_hub.events.bridge) — otherwise
    # this test would only prove the dashboard router's own publish call
    # fires, not that the funnel actually observes a real vault creation
    # the way it does in production.
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        registry = VaultRegistry(home / "registry", bus=VaultEventBus())
        app = create_app(
            HubConfig(),
            vault_registry=registry,
            vault_services={},
            home=home / "hub_home",
        )
        client = TestClient(app)

        create_response = client.post("/api/vaults", json={"key": "work"})
        assert create_response.status_code == 200

        status_response = client.get("/api/funnel/status")
        body = status_response.json()
        assert body["vault_created_at"] is not None
        assert body["client_connected_at"] is None
        assert body["first_memory_at"] is None


def test_funnel_status_is_read_only(tmp_path: Path) -> None:
    app = create_app(HubConfig(), vault_services={"work": FakeVaultService()}, home=tmp_path)
    client = TestClient(app)

    response = client.post("/api/funnel/status", json={})

    # 404, not 405: the dashboard's catch-all static mount (no build
    # present in this test environment) claims every unmatched route
    # before Starlette's router gets a chance to answer "405, wrong
    # method" for a path it does recognize — same shape as
    # `test_app_directory.py`/`test_app_messenger.py`'s identical check.
    assert response.status_code in (404, 405)
