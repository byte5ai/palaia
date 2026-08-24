from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.notifications.store import NotificationStore


def _client(tmp_path: Path) -> tuple[TestClient, NotificationStore]:
    store = NotificationStore(tmp_path / "n.sqlite3")
    app = create_app(HubConfig(), notification_store=store)
    return TestClient(app), store


def test_list_and_unread_count(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    store.create(title="Review needed", body="inbox/x")

    listed = client.get("/api/notifications")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "Review needed"

    count = client.get("/api/notifications/unread_count")
    assert count.json() == {"count": 1}


def test_mark_read(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    record = store.create(title="x")

    response = client.post(f"/api/notifications/{record.id}/read")
    assert response.status_code == 200
    assert response.json()["read"] is True
    assert client.get("/api/notifications/unread_count").json() == {"count": 0}


def test_mark_read_unknown_id_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.post("/api/notifications/9999/read").status_code == 404


def test_mark_all_read(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    store.create(title="a")
    store.create(title="b")

    response = client.post("/api/notifications/read_all")
    assert response.status_code == 200
    assert client.get("/api/notifications/unread_count").json() == {"count": 0}


def test_no_notification_store_leaves_endpoint_absent() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    assert client.get("/api/notifications").status_code == 404
