"""SPEC-403 deliverable #5's second sentence: "Automations can notify/webhook
on them (SPEC-307's action kinds compose — no new automation work here)".

This module is the evidence for the *no new work* half. The messenger adds
three names to the same event bus and nothing else; SPEC-307's dispatcher,
condition grammar and action kinds pick them up unchanged. Two things are
asserted:

1. An automation triggered on ``message.received`` fires and renders from
   the event's own ``data`` — including a condition on a metadata field, so
   "notify me only about high-urgency handoffs" works with no messenger
   -specific code anywhere in :mod:`palaia_hub.automations`.
2. What the automation can see is metadata only. There is no body to
   template from, and asking for one renders empty rather than leaking it —
   because the event never carried one in the first place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.automations.dispatcher import AutomationDispatcher
from palaia_hub.automations.models import ConditionClause, NotificationAction
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationStore
from palaia_hub.directory.service import DirectoryService
from palaia_hub.events.bus import EventBus, publish_event
from palaia_hub.messenger.service import MessengerService
from palaia_hub.notifications.store import NotificationStore

pytestmark = pytest.mark.anyio

SECRET_BODY = "the-body-that-must-not-travel"


async def _conversation(service: MessengerService, directory: DirectoryService) -> str:
    """One high-urgency handoff, sent and then checked. Returns B's handle."""
    a = await directory.register(scope="handing off")
    b = await directory.register(scope="taking over")
    await service.send(
        sender=a.session.handle,
        session_secret=a.session_secret,
        message_type="handoff",
        to=b.session.handle,
        subject="the billing refactor is yours",
        body=SECRET_BODY,
        urgency="high",
    )
    await service.check(b.session.handle, b.session_secret)
    return b.session.handle


async def test_an_automation_on_message_received_fires_from_metadata(
    tmp_path: Path,
    store: object,  # noqa: ARG001 - the MessengerStore fixture, used via `service`
    service: MessengerService,
    directory: DirectoryService,
) -> None:
    automations = AutomationStore(tmp_path / "automations")
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    dispatcher = AutomationDispatcher(
        automations, outbox, notification_store=notifications
    )
    automations.create(
        name="tell me about urgent handoffs",
        trigger_event="message.received",
        condition=[ConditionClause(field="data.urgency", op="equals", value="high")],
        action=NotificationAction(
            title_template="{{data.type}} from {{data.from}}: {{data.subject}}",
            body_template="{{data.body_bytes}} bytes waiting",
        ),
    )

    # The hub's real bus, wired exactly as `create_app` wires it.
    bus = EventBus()
    bus.on(dispatcher.on_event)
    service.publish = lambda name, data: publish_event(
        bus, name, origin="messenger", data=data
    )

    await _conversation(service, directory)
    delivered = await dispatcher.deliver_due()

    entries = notifications.list()
    assert delivered == 1
    assert len(entries) == 1
    assert entries[0].title.startswith("handoff from ")
    assert "the billing refactor is yours" in entries[0].title
    assert entries[0].body == f"{len(SECRET_BODY)} bytes waiting"


async def test_an_automation_cannot_template_a_body_that_never_travelled(
    tmp_path: Path,
    store: object,  # noqa: ARG001 - see above
    service: MessengerService,
    directory: DirectoryService,
) -> None:
    """The other side of the contract: even an automation that *asks* for
    ``data.body`` gets nothing, because no ``message.*`` event carries
    one."""
    automations = AutomationStore(tmp_path / "automations")
    outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
    notifications = NotificationStore(tmp_path / "notifications.sqlite3")
    dispatcher = AutomationDispatcher(
        automations, outbox, notification_store=notifications
    )
    automations.create(
        name="leak attempt",
        trigger_event="*",
        action=NotificationAction(
            title_template="body: {{data.body}}",
            body_template="{{data.body}}",
        ),
    )

    bus = EventBus()
    bus.on(dispatcher.on_event)
    service.publish = lambda name, data: publish_event(
        bus, name, origin="messenger", data=data
    )

    await _conversation(service, directory)
    await dispatcher.deliver_due()

    entries = notifications.list()
    assert entries  # the automation did fire
    for entry in entries:
        assert SECRET_BODY not in entry.title
        assert SECRET_BODY not in (entry.body or "")
