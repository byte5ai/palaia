"""REST surface for the automations editor (SPEC-307 deliverable #4)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationStore
from palaia_hub.config import HubConfig
from palaia_hub.notifications.store import NotificationStore


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        HubConfig(),
        automation_store=AutomationStore(tmp_path / "store"),
        automation_outbox=AutomationOutbox(tmp_path / "outbox.sqlite3"),
        notification_store=NotificationStore(tmp_path / "notifications.sqlite3"),
    )
    return TestClient(app)


_NOTIFICATION_BODY = {
    "name": "notify me",
    "trigger_event": "curator.capture.needs_review",
    "action": {"kind": "notification", "title_template": "{{data.permalink}} needs a look"},
}


def test_create_list_get_and_delete_an_automation(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post("/api/automations", json=_NOTIFICATION_BODY)
    assert created.status_code == 200
    automation_id = created.json()["id"]
    assert created.json()["enabled"] is True

    listed = client.get("/api/automations")
    assert [a["id"] for a in listed.json()] == [automation_id]

    fetched = client.get(f"/api/automations/{automation_id}")
    assert fetched.status_code == 200
    assert fetched.json()["action"]["kind"] == "notification"

    deleted = client.delete(f"/api/automations/{automation_id}")
    assert deleted.status_code == 204
    assert client.get("/api/automations").json() == []


def test_create_rejects_a_loop_guarded_trigger(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = {**_NOTIFICATION_BODY, "trigger_event": "automation.fired"}

    response = client.post("/api/automations", json=body)

    assert response.status_code == 400
    assert "loop" in response.json()["detail"]


def test_create_rejects_a_malformed_condition_with_a_plain_language_error(tmp_path: Path) -> None:
    client = _client(tmp_path)
    body = {
        **_NOTIFICATION_BODY,
        "condition": [{"field": "not_a_field", "op": "equals", "value": "x"}],
    }

    response = client.post("/api/automations", json=body)

    assert response.status_code == 400
    assert "not recognized" in response.json()["detail"]


def test_disable_and_enable_via_patch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    automation_id = client.post("/api/automations", json=_NOTIFICATION_BODY).json()["id"]

    disabled = client.patch(f"/api/automations/{automation_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_put_updates_the_action_and_trigger(tmp_path: Path) -> None:
    client = _client(tmp_path)
    automation_id = client.post("/api/automations", json=_NOTIFICATION_BODY).json()["id"]

    updated = client.put(
        f"/api/automations/{automation_id}",
        json={"trigger_event": "doctor.finding"},
    )
    assert updated.status_code == 200
    assert updated.json()["trigger_event"] == "doctor.finding"
    assert updated.json()["action"]["kind"] == "notification"  # untouched field kept


def test_operations_on_an_unknown_id_return_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/api/automations/nope").status_code == 404
    assert client.patch("/api/automations/nope", json={"enabled": False}).status_code == 404
    assert client.delete("/api/automations/nope").status_code == 404
    assert client.get("/api/automations/nope/deliveries").status_code == 404
    assert client.post("/api/automations/nope/test_fire", json={"data": {}}).status_code == 404


def test_test_fire_runs_the_pipeline_and_appears_in_the_delivery_log(tmp_path: Path) -> None:
    client = _client(tmp_path)
    automation_id = client.post("/api/automations", json=_NOTIFICATION_BODY).json()["id"]

    fired = client.post(
        f"/api/automations/{automation_id}/test_fire",
        json={"data": {"permalink": "inbox/x"}},
    )
    assert fired.status_code == 200
    body = fired.json()
    assert body["test"] is True
    assert body["status"] == "delivered"

    log = client.get(f"/api/automations/{automation_id}/deliveries")
    assert log.status_code == 200
    assert len(log.json()) == 1
    assert log.json()[0]["test"] is True


def test_the_hub_with_no_automation_store_leaves_the_endpoint_absent() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    assert client.get("/api/automations").status_code == 404
