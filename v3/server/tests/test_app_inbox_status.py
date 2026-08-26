"""SPEC-107 deliverable #3: the ``/api/vaults/{vault_key}/inbox_status`` REST
endpoint, independent of any MCP gateway being mounted.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.fake_vault import FakeVaultService


def test_inbox_status_endpoint_absent_without_vault_services() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)
    response = client.get("/api/vaults/work/inbox_status")
    assert response.status_code == 404


def test_inbox_status_endpoint_unknown_vault_key_is_404() -> None:
    app = create_app(HubConfig(), vault_services={"work": FakeVaultService()})
    client = TestClient(app)
    response = client.get("/api/vaults/personal/inbox_status")
    assert response.status_code == 404


def test_inbox_status_endpoint_reports_zero_with_no_captures() -> None:
    app = create_app(HubConfig(), vault_services={"work": FakeVaultService()})
    client = TestClient(app)
    response = client.get("/api/vaults/work/inbox_status")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["oldest_age_seconds"] is None


def test_inbox_status_endpoint_reflects_captures() -> None:
    service = FakeVaultService()
    app = create_app(HubConfig(), vault_services={"work": service})
    client = TestClient(app)

    asyncio.run(
        service.capture(
            what_it_concerns="API Gateway",
            why_keep="the limit was chosen deliberately",
            content="raw detail here",
        )
    )

    response = client.get("/api/vaults/work/inbox_status")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["oldest_capture_id"] is not None
