"""``create_app(stash_service=...)`` wiring (SPEC-202): the ``/mcp/stash``
mount, the ``/api/stash`` REST mirror, and both reading/writing the same
backing store."""

from __future__ import annotations

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore


def test_stash_absent_by_default() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    response = client.get("/api/stash/")

    assert response.status_code == 404


def test_stash_rest_mirror_round_trips() -> None:
    service = StashService(StashStore(":memory:"))
    app = create_app(HubConfig(), stash_service=service)
    client = TestClient(app)

    put = client.put("/api/stash/jobs/job-1", json={"value": {"status": "running"}})
    assert put.status_code == 200
    assert put.json()["size_bytes"] > 0

    got = client.get("/api/stash/jobs/job-1")
    assert got.status_code == 200
    body = got.json()
    assert body["found"] is True
    assert body["entry"]["value"] == {"status": "running"}

    status = client.get("/api/stash/")
    assert status.status_code == 200
    assert status.json()["total_entries"] == 1

    deleted = client.delete("/api/stash/jobs/job-1")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_stash_events_are_wired_onto_the_hub_event_bus() -> None:
    service = StashService(StashStore(":memory:"))
    app = create_app(HubConfig(), stash_service=service)

    assert service.publish is not None
    bus = app.state.event_bus
    queue = bus.subscribe()
    service.publish("stash.set", {"namespace": "jobs", "key": "job-1"})

    event = queue.get_nowait()
    assert event.event == "stash.set"
    assert event.origin == "stash"
    assert event.data["namespace"] == "jobs"
    assert event.data["key"] == "job-1"
