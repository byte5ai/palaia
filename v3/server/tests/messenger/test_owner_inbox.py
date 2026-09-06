"""Issue #365: the owner is a recipient.

``messenger_send to="owner"`` used to fail with "no session is registered at
handle 'owner'": the owner has no directory row, so an owner message that
expected a reply could not be answered to the owner at all. The owner now
has an inbox — read over ``GET /api/messenger/inbox``, acked over ``POST
/api/messenger/inbox/{id}/ack`` — and every envelope for it raises a
notification in the dashboard's notification center.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.directory.service import DirectoryService
from palaia_hub.messenger.models import OWNER_HANDLE, InvalidEnvelopeError
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore
from palaia_hub.messenger_api import build_messenger_router
from palaia_hub.notifications.store import NotificationStore

pytestmark = pytest.mark.anyio


async def _session(directory: DirectoryService) -> tuple[str, str]:
    result = await directory.register(scope="ops", ttl_seconds=60)
    return result.session.handle, result.session_secret


async def test_a_session_can_write_to_the_owner_who_gets_a_notification(
    directory: DirectoryService, store: MessengerStore, tmp_path: Path
) -> None:
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    service = MessengerService(store, directory, notifications=notifications)
    handle, secret = await _session(directory)

    sent = await service.send(
        sender=handle,
        session_secret=secret,
        message_type="question",
        to=OWNER_HANDLE,
        subject="Need a decision",
        body="Ship the release today?",
        expects_reply=True,
    )

    assert sent.recipients == [OWNER_HANDLE]
    [notification] = notifications.list()
    assert notification.source == "messenger"
    assert "Need a decision" in notification.title
    assert handle in notification.title

    inbox = await service.owner_inbox()
    assert [envelope.id for envelope in inbox.envelopes] == [sent.envelopes[0].id]
    assert inbox.envelopes[0].body == "Ship the release today?"

    acked = await service.owner_ack(sent.envelopes[0].id)
    assert acked.acked is True
    assert (await service.owner_inbox()).envelopes == []
    notifications.close()


async def test_a_reply_to_the_owner_closes_the_loop(
    directory: DirectoryService, store: MessengerStore
) -> None:
    service = MessengerService(store, directory)
    handle, secret = await _session(directory)
    asked = await service.send_as_owner(
        message_type="question", to=handle, subject="Status?", expects_reply=True
    )
    received = await service.check(handle, secret)
    assert [e.id for e in received.envelopes] == [asked.envelopes[0].id]

    reply = await service.send(
        sender=handle,
        session_secret=secret,
        message_type="inform",
        to=OWNER_HANDLE,
        subject="Re: Status?",
        body="All green.",
        reply_to=asked.envelopes[0].id,
    )

    assert reply.recipients == [OWNER_HANDLE]
    inbox = await service.owner_inbox()
    assert inbox.envelopes[0].reply_to == asked.envelopes[0].id


async def test_the_owner_cannot_address_the_owner(
    directory: DirectoryService, store: MessengerStore
) -> None:
    service = MessengerService(store, directory)
    with pytest.raises(InvalidEnvelopeError, match="cannot send to 'owner'"):
        await service.send_as_owner(message_type="inform", to=OWNER_HANDLE, subject="hi")


async def test_the_owner_inbox_is_served_over_the_admin_surface(
    directory: DirectoryService, store: MessengerStore
) -> None:
    service = MessengerService(store, directory)
    handle, secret = await _session(directory)
    sent = await service.send(
        sender=handle,
        session_secret=secret,
        message_type="inform",
        to=OWNER_HANDLE,
        subject="FYI",
        body="done",
    )
    app = FastAPI()
    app.include_router(build_messenger_router(service))
    client = TestClient(app)

    inbox = client.get("/api/messenger/inbox")
    assert inbox.status_code == 200, inbox.text
    assert [e["id"] for e in inbox.json()["envelopes"]] == [sent.envelopes[0].id]
    assert inbox.json()["envelopes"][0]["body"] == "done"

    assert client.post(f"/api/messenger/inbox/{sent.envelopes[0].id}/ack").status_code == 200
    assert client.get("/api/messenger/inbox").json()["envelopes"] == []
    assert client.post("/api/messenger/inbox/no-such-envelope/ack").status_code == 404
