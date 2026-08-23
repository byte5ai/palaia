from __future__ import annotations

import asyncio

import pytest

from palaia_hub.events.bus import EventBus, publish_event, publish_from_hook
from palaia_hub.events.schema import Envelope


def test_publish_event_builds_and_delivers_an_envelope() -> None:
    bus = EventBus()
    received: list[Envelope] = []
    bus.on(received.append)

    envelope = publish_event(bus, "hub.started", origin="hub", data={"version": "1"})

    assert received == [envelope]
    assert envelope.event == "hub.started"


def test_publish_from_hook_promotes_vault_and_permalink_from_data() -> None:
    bus = EventBus()
    received: list[Envelope] = []
    bus.on(received.append)

    publish_from_hook(
        bus,
        "inbox.captured",
        {"vault": "work", "permalink": "inbox/x", "capture_id": "cap-1"},
        origin="inbox",
    )

    assert len(received) == 1
    envelope = received[0]
    assert envelope.vault == "work"
    assert envelope.permalink == "inbox/x"
    assert envelope.data["capture_id"] == "cap-1"
    # data is left intact too, for a consumer reading only .data
    assert envelope.data["vault"] == "work"


def test_on_returns_an_unsubscribe_callable() -> None:
    bus = EventBus()
    received: list[Envelope] = []
    unsubscribe = bus.on(received.append)

    unsubscribe()
    publish_event(bus, "hub.started", origin="hub", data={})

    assert received == []


def test_a_raising_callback_does_not_break_other_subscribers() -> None:
    bus = EventBus()
    received: list[Envelope] = []

    def bad(_: Envelope) -> None:
        raise RuntimeError("boom")

    bus.on(bad)
    bus.on(received.append)

    publish_event(bus, "hub.started", origin="hub", data={})

    assert len(received) == 1


@pytest.mark.anyio
async def test_sse_queue_subscriber_receives_published_envelopes() -> None:
    bus = EventBus()
    queue = bus.subscribe()

    publish_event(bus, "hub.started", origin="hub", data={"version": "1"})

    envelope = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert envelope.event == "hub.started"
    bus.unsubscribe(queue)


@pytest.mark.anyio
async def test_a_slow_sse_subscriber_drops_its_oldest_event_rather_than_blocking() -> None:
    bus = EventBus(max_queue=2)
    queue = bus.subscribe()

    for i in range(5):
        publish_event(bus, "hub.started", origin="hub", data={"i": i})

    assert queue.qsize() == 2
    first = await queue.get()
    second = await queue.get()
    # the oldest events were dropped; the newest two survive
    assert first.data["i"] == 3
    assert second.data["i"] == 4
    bus.unsubscribe(queue)


def test_subscriber_count_reflects_sse_queues_not_callbacks() -> None:
    bus = EventBus()
    bus.on(lambda _e: None)
    assert bus.subscriber_count == 0

    queue = bus.subscribe()
    assert bus.subscriber_count == 1

    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0
