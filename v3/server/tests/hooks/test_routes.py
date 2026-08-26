from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.hooks.outbox import HookOutbox
from palaia_hub.hooks.store import HookStore


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        HubConfig(),
        hook_store=HookStore(tmp_path),
        hook_outbox=HookOutbox(tmp_path / "outbox.sqlite3"),
    )
    return TestClient(app)


def test_create_list_and_delete_a_hook(tmp_path: Path) -> None:
    client = _client(tmp_path)

    created = client.post(
        "/api/hooks", json={"url": "https://example.com/hook", "events": ["hub.started"]}
    )
    assert created.status_code == 200
    body = created.json()
    assert body["secret"]
    hook_id = body["info"]["id"]

    listed = client.get("/api/hooks")
    assert listed.status_code == 200
    assert [h["id"] for h in listed.json()] == [hook_id]
    # The secret never appears on the list surface.
    assert "secret" not in listed.json()[0]

    deleted = client.delete(f"/api/hooks/{hook_id}")
    assert deleted.status_code == 204
    assert client.get("/api/hooks").json() == []


def test_disable_and_enable_a_hook(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/hooks", json={"url": "https://example.com/hook"})
    hook_id = created.json()["info"]["id"]

    disabled = client.patch(f"/api/hooks/{hook_id}", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    enabled = client.patch(f"/api/hooks/{hook_id}", json={"enabled": True})
    assert enabled.json()["enabled"] is True


def test_create_rejects_an_invalid_url(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post("/api/hooks", json={"url": "not-a-url"})

    assert response.status_code == 400


def test_operations_on_an_unknown_hook_id_return_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.patch("/api/hooks/nope", json={"enabled": False}).status_code == 404
    assert client.delete("/api/hooks/nope").status_code == 404
    assert client.get("/api/hooks/nope/dead_letters").status_code == 404


def test_dead_letters_are_visible_via_rest(tmp_path: Path) -> None:
    """SPEC-201 acceptance: 'permanent failure -> dead-letter visible via REST'."""
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    store = HookStore(tmp_path)
    created = store.create("https://example.com/hook")
    outbox.enqueue(
        hook_id=created.info.id,
        event_id="ev-1",
        event_name="hub.started",
        payload=b"{}",
        signature="sig",
    )
    row = outbox.claim_due()[0]
    outbox.mark_dead(row.id, error="HTTP 500")

    app = create_app(HubConfig(), hook_store=store, hook_outbox=outbox)
    client = TestClient(app)

    response = client.get(f"/api/hooks/{created.info.id}/dead_letters")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event_id"] == "ev-1"
    assert payload[0]["last_error"] == "HTTP 500"


def test_the_hub_no_hook_store_leaves_hooks_endpoint_absent(tmp_path: Path) -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    assert client.get("/api/hooks").status_code == 404
