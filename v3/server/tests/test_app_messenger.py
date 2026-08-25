"""``create_app(messenger_service=...)`` wiring (SPEC-403): the
``/mcp/messenger`` mount, the read-only ``/api/messenger`` REST mirror
(deliverable #6) and its ``message.*`` events landing on the hub's event
bus.

The mirror's contract, asserted here rather than only documented: the two
listing routes carry **no** body, and exactly one route — the owner's
envelope read — does.
"""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore


def _service() -> tuple[MessengerService, DirectoryService]:
    directory = DirectoryService(DirectoryStore(":memory:"))
    return MessengerService(MessengerStore(":memory:"), directory), directory


def _conversation(service: MessengerService, directory: DirectoryService) -> dict[str, str]:
    """One request + one reply between two registered sessions."""

    async def run() -> dict[str, str]:
        a = await directory.register(scope="reviewing")
        b = await directory.register(scope="refactoring")
        request = await service.send(
            sender=a.session.handle,
            session_secret=a.session_secret,
            message_type="request",
            to=b.session.handle,
            subject="please rename it",
            body="the-body-nobody-else-should-see",
            expects_reply=True,
        )
        await service.check(b.session.handle, b.session_secret)
        reply = await service.send(
            sender=b.session.handle,
            session_secret=b.session_secret,
            message_type="inform",
            to=a.session.handle,
            subject="renamed",
            body="done",
            reply_to=request.envelopes[0].id,
        )
        return {
            "a": a.session.handle,
            "b": b.session.handle,
            "request_id": request.envelopes[0].id,
            "reply_id": reply.envelopes[0].id,
        }

    return asyncio.run(run())


def test_messenger_absent_by_default() -> None:
    app = create_app(HubConfig())
    client = TestClient(app)

    assert client.get("/api/messenger/").status_code == 404


def test_messenger_rest_mirror_is_read_only() -> None:
    """Deliverable #6: the listing surface itself has no write verb —
    sending and checking *as a session* only ever happen over MCP, from
    the session itself, holding its own session secret. (SPEC-405 adds two
    write routes elsewhere on this mount — ``POST /send``, sending *as the
    owner*, and ``POST /threads/{id}/end`` — covered in
    ``test_owner_controls.py`` below; neither is this root listing route.)
    """
    service, _ = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)

    for method in ("post", "put", "delete", "patch"):
        response = getattr(client, method)("/api/messenger/")
        # 405 from FastAPI's router; 404 when a dashboard build is present
        # (see test_app_directory.py for the same note). Either way: refused.
        assert response.status_code in (404, 405)


def test_flows_are_metadata_only() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)
    ids = _conversation(service, directory)

    response = client.get("/api/messenger/")
    assert response.status_code == 200
    flows = response.json()["flows"]
    assert len(flows) == 2
    for flow in flows:
        assert "body" not in flow
        assert "body_bytes" in flow
    assert "the-body-nobody-else-should-see" not in response.text
    assert {flow["id"] for flow in flows} == {ids["request_id"], ids["reply_id"]}


def test_flows_filter_by_handle_type_and_state() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)
    ids = _conversation(service, directory)

    by_handle = client.get("/api/messenger/", params={"handle": ids["a"]})
    assert len(by_handle.json()["flows"]) == 2  # sender of one, recipient of the other

    by_type = client.get("/api/messenger/", params={"type": "request"})
    assert [flow["id"] for flow in by_type.json()["flows"]] == [ids["request_id"]]

    delivered = client.get("/api/messenger/", params={"state": "delivered"})
    assert [flow["id"] for flow in delivered.json()["flows"]] == [ids["request_id"]]

    limited = client.get("/api/messenger/", params={"limit": 1})
    assert len(limited.json()["flows"]) == 1


def test_outbox_route_is_the_sent_side_only() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)
    ids = _conversation(service, directory)

    a_outbox = client.get(f"/api/messenger/outbox/{ids['a']}")
    assert a_outbox.status_code == 200
    flows = a_outbox.json()["flows"]
    assert [flow["id"] for flow in flows] == [ids["request_id"]]
    assert flows[0]["recipient"] == ids["b"]
    assert flows[0]["state"] == "delivered"
    assert "body" not in flows[0]

    b_outbox = client.get(f"/api/messenger/outbox/{ids['b']}")
    assert [flow["id"] for flow in b_outbox.json()["flows"]] == [ids["reply_id"]]

    assert client.get("/api/messenger/outbox/nobody").json()["flows"] == []


def test_thread_route_is_metadata_only() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)
    ids = _conversation(service, directory)

    response = client.get(f"/api/messenger/threads/{ids['reply_id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["root_id"] == ids["request_id"]
    assert [flow["id"] for flow in payload["flows"]] == [ids["request_id"], ids["reply_id"]]
    for flow in payload["flows"]:
        assert "body" not in flow
    assert "the-body-nobody-else-should-see" not in response.text


def test_the_envelope_route_is_the_one_place_a_body_appears() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)
    ids = _conversation(service, directory)

    response = client.get(f"/api/messenger/envelopes/{ids['request_id']}")
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["envelope"]["body"] == "the-body-nobody-else-should-see"
    assert item["envelope"]["from"] == ids["a"]
    assert item["recipient"] == ids["b"]
    assert item["state"] == "delivered"


def test_unknown_ids_are_404_not_500() -> None:
    service, _ = _service()
    app = create_app(HubConfig(), messenger_service=service)
    client = TestClient(app)

    assert client.get("/api/messenger/threads/nope").status_code == 404
    assert client.get("/api/messenger/envelopes/nope").status_code == 404


def test_messenger_events_are_wired_onto_the_hub_event_bus() -> None:
    service, _ = _service()
    app = create_app(HubConfig(), messenger_service=service)

    assert service.publish is not None
    bus = app.state.event_bus
    queue = bus.subscribe()
    service.publish("message.received", {"id": "abc123", "subject": "s"})

    event = queue.get_nowait()
    assert event.event == "message.received"
    assert event.origin == "messenger"
    assert event.data["id"] == "abc123"


# -- owner controls (SPEC-405 deliverable #2), over the real app -------------


def test_send_as_owner_route_delivers_with_the_owner_handle() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service, directory_service=directory)
    client = TestClient(app)

    async def _recipient() -> tuple[str, str]:
        registered = await directory.register(scope="waiting on the owner")
        return registered.session.handle, registered.session_secret

    recipient, recipient_secret = asyncio.run(_recipient())

    response = client.post(
        "/api/messenger/send",
        json={"to": recipient, "subject": "a note from the owner", "body": "hello"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["envelopes"][0]["from"] == "owner"

    delivered = asyncio.run(service.check(recipient, recipient_secret))
    assert [e.subject for e in delivered.envelopes] == ["a note from the owner"]
    assert delivered.envelopes[0].from_ == "owner"


def test_send_as_owner_route_rejects_an_over_long_subject() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service, directory_service=directory)
    client = TestClient(app)

    response = client.post(
        "/api/messenger/send", json={"to": "someone", "subject": "s" * 300}
    )
    assert response.status_code == 422  # the schema itself refuses it


def test_send_as_owner_route_names_an_unknown_recipient_in_the_body() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service, directory_service=directory)
    client = TestClient(app)

    response = client.post(
        "/api/messenger/send", json={"to": "nobody-registered", "subject": "hi"}
    )
    assert response.status_code == 400
    assert "nobody-registered" in response.json()["detail"]


def test_end_conversation_route_expires_the_undelivered_copy() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service, directory_service=directory)
    client = TestClient(app)

    async def _thread_with_one_undelivered_followup() -> dict[str, str]:
        a = await directory.register(scope="reviewing")
        b = await directory.register(scope="refactoring")
        request = await service.send(
            sender=a.session.handle,
            session_secret=a.session_secret,
            message_type="request",
            to=b.session.handle,
            subject="please rename it",
            expects_reply=True,
        )
        request_id = request.envelopes[0].id
        # b checks (delivers) the request but never replies — this copy
        # stays `delivered`, so ending the conversation must not touch it.
        await service.check(b.session.handle, b.session_secret)
        # b sends a follow-up in the same thread that a never checks — this
        # one stays `pending`, which is what "undelivered" means.
        followup = await service.send(
            sender=b.session.handle,
            session_secret=b.session_secret,
            message_type="inform",
            to=a.session.handle,
            subject="unread follow-up",
            reply_to=request_id,
        )
        return {"request_id": request_id, "followup_id": followup.envelopes[0].id}

    ids = asyncio.run(_thread_with_one_undelivered_followup())

    response = client.post(f"/api/messenger/threads/{ids['request_id']}/end")
    assert response.status_code == 200
    payload = response.json()
    assert payload["root_id"] == ids["request_id"]
    assert [e["id"] for e in payload["expired"]] == [ids["followup_id"]]

    # The already-delivered request is untouched.
    thread = client.get(f"/api/messenger/threads/{ids['request_id']}")
    assert [f["id"] for f in thread.json()["flows"]] == [ids["request_id"]]


def test_end_conversation_route_on_an_unknown_id_is_404() -> None:
    service, directory = _service()
    app = create_app(HubConfig(), messenger_service=service, directory_service=directory)
    client = TestClient(app)

    response = client.post("/api/messenger/threads/no-such-id/end")
    assert response.status_code == 404
