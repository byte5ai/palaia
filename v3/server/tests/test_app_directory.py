"""``create_app(directory_service=...)`` wiring (SPEC-402): the
``/mcp/directory`` mount, the read-only ``/api/directory`` REST mirror, and
its ``session.*`` events landing on the hub's event bus."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore


def test_directory_absent_by_default() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/directory/")

    assert response.status_code == 404


def test_directory_rest_mirror_is_read_only() -> None:
    """Deliverable #4: 'list/query only'. There is no POST/PUT/DELETE on
    this REST surface at all — mutations only ever come from MCP callers
    holding their own session secret."""
    service = DirectoryService(DirectoryStore(":memory:"))
    app = create_app(HubConfig(), directory_service=service)
    client = TestClient(app)

    for method in ("post", "put", "delete", "patch"):
        response = getattr(client, method)("/api/directory/")
        # 405 from FastAPI's router; 404 when a dashboard build is present
        # (the SPA catch-all mount answers unmatched backend methods before
        # the router's method-not-allowed logic — see static.py). Either
        # way: refused, which is what "read-only" means.
        assert response.status_code in (404, 405)


def test_directory_rest_mirror_lists_and_queries() -> None:
    service = DirectoryService(DirectoryStore(":memory:"))
    app = create_app(HubConfig(), directory_service=service)
    client = TestClient(app)

    asyncio.run(service.register(scope="refactoring billing", platform="claude-code"))

    listing = client.get("/api/directory/")
    assert listing.status_code == 200
    assert len(listing.json()["sessions"]) == 1

    query = client.get("/api/directory/query", params={"scope_contains": "billing"})
    assert query.status_code == 200
    assert len(query.json()["sessions"]) == 1

    query_miss = client.get("/api/directory/query", params={"scope_contains": "nope"})
    assert query_miss.json()["sessions"] == []


def test_directory_events_are_wired_onto_the_hub_event_bus() -> None:
    service = DirectoryService(DirectoryStore(":memory:"))
    app = create_app(HubConfig(), directory_service=service)

    assert service.publish is not None
    bus = app.state.event_bus
    queue = bus.subscribe()
    service.publish("session.registered", {"handle": "abc123"})

    event = queue.get_nowait()
    assert event.event == "session.registered"
    assert event.origin == "directory"
    assert event.data["handle"] == "abc123"
