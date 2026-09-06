"""Issue #338: an automation's own output never becomes an automation's input.

A ``memory_write`` lands a note, which publishes ``memory.entry.created``;
a ``stash_set`` publishes ``stash.set``. Before the fix the only loop guard
was the ``automation.*`` prefix, so an automation on ``memory.entry.created``
(or ``"*"``) that wrote a note fired on its own note, forever, one commit per
iteration; and ``"*"`` also matched the 15-second ``health`` heartbeat.

These tests wire the real buses the hub wires — the vault bus bridged onto
the hub bus, the stash publishing onto the hub bus, the dispatcher
subscribed to it — and assert that one triggering event yields exactly one
delivery.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palaia_hub.automations.dispatcher import (
    MAX_FIRES_PER_MINUTE,
    AutomationDispatcher,
    _matches_trigger,
)
from palaia_hub.automations.models import MemoryWriteAction, NotificationAction, StashSetAction
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationStore
from palaia_hub.events.bridge import bridge_vault_events
from palaia_hub.events.bus import EventBus, publish_event, publish_from_hook
from palaia_hub.events.schema import Envelope
from palaia_hub.notifications.store import NotificationStore
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore
from palaia_hub.vault import EventBus as VaultEventBus
from palaia_hub.vault import VaultRegistry

pytestmark = pytest.mark.anyio


class _Rig:
    """The hub's wiring in miniature: one public bus, every producer on it."""

    def __init__(self, tmp_path: Path) -> None:
        self.hub_bus = EventBus()
        self.vault_bus = VaultEventBus()
        bridge_vault_events(self.vault_bus, self.hub_bus)
        self.registry = VaultRegistry(tmp_path / "home", bus=self.vault_bus)
        self.stash = StashService(
            StashStore(tmp_path / "stash.sqlite3"),
            publish=lambda name, data: publish_from_hook(self.hub_bus, name, data, origin="stash"),
        )
        self.notifications = NotificationStore(tmp_path / "notifications.sqlite3")
        self.store = AutomationStore(tmp_path / "automations")
        self.outbox = AutomationOutbox(tmp_path / "outbox.sqlite3")
        self.dispatcher = AutomationDispatcher(
            self.store,
            self.outbox,
            vault_registry=self.registry,
            stash_service=self.stash,
            notification_store=self.notifications,
            emit=lambda name, data: publish_from_hook(
                self.hub_bus, name, data, origin="automations"
            ),
        )
        self.hub_bus.on(self.dispatcher.on_event)
        self.seen: list[Envelope] = []
        self.hub_bus.on(self.seen.append)

    async def drain(self) -> int:
        """Deliver until the queue is empty; return how many deliveries ran."""
        total = 0
        for _ in range(20):
            delivered = await self.dispatcher.deliver_due()
            if delivered == 0:
                break
            total += delivered
            await asyncio.sleep(0)
        return total


async def test_a_memory_write_does_not_retrigger_an_automation_on_note_events(
    tmp_path: Path,
) -> None:
    rig = _Rig(tmp_path)
    await rig.registry.create("work", tmp_path / "vaults/work")
    rig.store.create(
        name="log every note",
        trigger_event="memory.entry.created",
        action=MemoryWriteAction(
            vault="work",
            what_it_concerns_template="note {{data.path}}",
            why_keep_template="An audit line per note.",
            content_template="{{data.path}} was created.",
        ),
    )
    engine = await rig.registry.get("work")

    # One real note from outside — the trigger.
    await engine.write_note("notes/seed", body="seed\n", title="Seed")
    delivered = await rig.drain()

    assert delivered == 1, "the automation's own note must not fire it again"
    assert rig.outbox.count_pending() == 0
    rows = rig.outbox.list_for_automation(rig.store.list_info()[0].id, limit=500)
    assert [row.status for row in rows] == ["delivered"]
    created = [e for e in rig.seen if e.event == "memory.entry.created"]
    # Both notes were published (the seed and the automation's own) — the
    # second simply matched nothing.
    assert len(created) == 2
    assert len([e for e in rig.seen if e.event == "automation.fired"]) == 1


async def test_a_stash_set_does_not_retrigger_a_wildcard_automation(tmp_path: Path) -> None:
    """The recipe from the issue: trigger ``"*"``, action ``stash_set``."""
    rig = _Rig(tmp_path)
    rig.store.create(
        name="remember the last event",
        trigger_event="*",
        action=StashSetAction(namespace="events", key_template="last", value_template="{{event}}"),
    )

    publish_event(rig.hub_bus, "doctor.finding", origin="test", data={"code": "x"})
    delivered = await rig.drain()

    assert delivered == 1
    assert rig.outbox.count_pending() == 0
    assert len([e for e in rig.seen if e.event == "stash.set"]) == 1
    entry = await rig.stash.get("events", "last")
    assert entry.found


async def test_events_caused_by_one_automation_do_not_fire_another(tmp_path: Path) -> None:
    """A→B→A chains are the same loop with an extra hop: nothing caused by an
    automation's action triggers any automation."""
    rig = _Rig(tmp_path)
    rig.store.create(
        name="A: stash on findings",
        trigger_event="doctor.finding",
        action=StashSetAction(namespace="a", key_template="k", value_template="v"),
    )
    rig.store.create(
        name="B: notify on stash",
        trigger_event="stash.set",
        action=NotificationAction(title_template="stash changed", body_template="{{data.key}}"),
    )

    publish_event(rig.hub_bus, "doctor.finding", origin="test", data={"code": "x"})
    delivered = await rig.drain()

    assert delivered == 1
    statuses = sorted(
        row.status
        for info in rig.store.list_info()
        for row in rig.outbox.list_for_automation(info.id, limit=500)
    )
    assert statuses == ["delivered"], "only A fired; B saw an automation-caused event"

    # B still works for a stash.set that a *person* (or client) caused.
    await rig.stash.set("a", "manual", "value")
    assert await rig.drain() == 1


def test_a_wildcard_trigger_skips_the_health_heartbeat_but_an_explicit_one_matches() -> None:
    health = Envelope(event="health", data={}, origin="hub")
    real = Envelope(event="stash.set", data={}, origin="stash")

    assert not _matches_trigger("*", health)
    assert _matches_trigger("*", real)
    assert _matches_trigger("health", health)
    assert not _matches_trigger(
        "automation.fired", Envelope(event="automation.fired", data={}, origin="automations")
    )


async def test_an_automation_is_throttled_after_its_minute_of_fires(tmp_path: Path) -> None:
    rig = _Rig(tmp_path)
    rig.store.create(
        name="noisy",
        trigger_event="doctor.finding",
        action=NotificationAction(title_template="finding", body_template="{{data.code}}"),
    )
    automation_id = rig.store.list_info()[0].id

    for index in range(MAX_FIRES_PER_MINUTE + 15):
        publish_event(rig.hub_bus, "doctor.finding", origin="test", data={"code": str(index)})

    assert rig.outbox.count_pending(automation_id) == MAX_FIRES_PER_MINUTE
    assert rig.outbox.count_recent(automation_id, window_seconds=60) == MAX_FIRES_PER_MINUTE
