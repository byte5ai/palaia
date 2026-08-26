"""SPEC-404 deliverable #4: the `message.received` push recipe.

"No new delivery system" is the deliverable's own constraint, and this test
is the evidence for it: the messenger already publishes `message.received`
onto the hub's one event bus (SPEC-403 deliverable #5), and SPEC-201's
outbound-webhook mechanism already matches a hook against any event name —
so "notify my other tooling when a message arrives" needs nothing new,
just a hook registered on that one event name. `docs/messenger.md` documents
the exact `POST /api/hooks` call this test drives directly against the real
dispatcher/outbox pair, the same real-local-receiver pattern
`hooks/test_delivery.py` uses for its own acceptance criteria.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from webhook_receiver import LocalReceiver

from palaia_hub.directory.service import DirectoryService
from palaia_hub.events.bus import EventBus, publish_event
from palaia_hub.hooks.delivery import HookDispatcher
from palaia_hub.hooks.outbox import HookOutbox
from palaia_hub.hooks.signing import verify
from palaia_hub.hooks.store import HookStore
from palaia_hub.messenger.service import MessengerService

pytestmark = pytest.mark.anyio

SECRET_BODY = "the-body-that-must-not-travel-over-the-webhook-either"


async def test_a_message_received_webhook_delivers_with_a_valid_signature(
    tmp_path: Path,
    service: MessengerService,
    directory: DirectoryService,
    local_receiver: LocalReceiver,
) -> None:
    """The recipe end to end: register the hook the way `docs/messenger.md`
    tells an operator to, then have two real sessions exchange a message
    and let the real hook pipeline carry the notification — no messenger-
    specific code anywhere in :mod:`palaia_hub.hooks`."""
    hook_store = HookStore(tmp_path)
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    dispatcher = HookDispatcher(hook_store, outbox)
    created = hook_store.create(local_receiver.url, ["message.received"])

    # The hub's real bus, wired exactly as `create_app` wires it (see
    # `test_automations_compose.py` for the sibling case with automations
    # instead of a webhook).
    bus = EventBus()
    bus.on(dispatcher.on_event)
    service.publish = lambda name, data: publish_event(
        bus, name, origin="messenger", data=data
    )

    a = await directory.register(scope="build pipeline")
    b = await directory.register(scope="notify my other tooling")
    await service.send(
        sender=a.session.handle,
        session_secret=a.session_secret,
        message_type="inform",
        to=b.session.handle,
        subject="build finished",
        body=SECRET_BODY,
    )
    await service.check(b.session.handle, b.session_secret)

    delivered = await dispatcher.deliver_due()
    await dispatcher.aclose()

    assert delivered == 1
    assert len(local_receiver.requests) == 1
    request = local_receiver.requests[0]
    signature = request.headers["X-Palaia-Signature"]
    assert verify(created.secret, request.body, signature)

    body = json.loads(request.body)
    assert body["event"] == "message.received"
    assert body["data"]["subject"] == "build finished"
    assert body["data"]["type"] == "inform"
    # The same "never the body" contract as the bus itself, still true one
    # hop further down the SPEC-201 outbox — a webhook payload built from
    # anything but `EnvelopeMetadata` would be a second place that rule has
    # to be remembered.
    assert "body" not in body["data"]
    assert SECRET_BODY not in request.body.decode("utf-8")


async def test_a_hook_scoped_to_a_different_event_never_fires(
    tmp_path: Path,
    service: MessengerService,
    directory: DirectoryService,
    local_receiver: LocalReceiver,
) -> None:
    """The other half of "no new delivery system": ordinary event-filter
    behaviour applies to `message.*` exactly as it does to anything else on
    the bus — a hook not asking for this event does not receive it."""
    hook_store = HookStore(tmp_path)
    outbox = HookOutbox(tmp_path / "outbox.sqlite3")
    dispatcher = HookDispatcher(hook_store, outbox)
    hook_store.create(local_receiver.url, ["memory.entry.created"])

    bus = EventBus()
    bus.on(dispatcher.on_event)
    service.publish = lambda name, data: publish_event(
        bus, name, origin="messenger", data=data
    )

    a = await directory.register(scope="a")
    b = await directory.register(scope="b")
    await service.send(
        sender=a.session.handle,
        session_secret=a.session_secret,
        message_type="inform",
        to=b.session.handle,
        subject="not for this hook",
    )
    await service.check(b.session.handle, b.session_secret)

    delivered = await dispatcher.deliver_due()
    await dispatcher.aclose()

    assert delivered == 0
    assert local_receiver.requests == []
