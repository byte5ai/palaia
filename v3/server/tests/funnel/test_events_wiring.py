"""``wire_funnel_tracking`` reacts to the real public events (SPEC-504),
independent of any HTTP surface — the same "plain in-process bus consumer"
shape as the hooks/automations dispatchers it sits next to in
``palaia_hub.app``.
"""

from __future__ import annotations

from pathlib import Path

from palaia_hub.events.bus import EventBus, publish_event
from palaia_hub.funnel import FunnelStore, wire_funnel_tracking


def test_hub_started_event_records_the_start_line(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "hub.started", origin="hub", data={})

    assert store.status().hub_started_at is not None


def test_vault_created_event_records_that_step(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "memory.vault.created", origin="dashboard", data={"key": "work"})

    assert store.status().vault_created_at is not None


def test_client_connected_event_records_that_step(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "client.connected", origin="auth", data={"token_id": "t1"})

    assert store.status().client_connected_at is not None


def test_first_memory_event_records_that_step(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "memory.entry.created", origin="vault", data={"kind": "created"})

    assert store.status().first_memory_at is not None


def test_unrelated_events_are_ignored(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "gateway.upstream.up", origin="gateway", data={})
    publish_event(bus, "health", origin="hub", data={})

    status = store.status()
    assert status.hub_started_at is None
    assert status.vault_created_at is None
    assert status.client_connected_at is None
    assert status.first_memory_at is None


def test_only_the_first_memory_entry_created_event_counts(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "memory.entry.created", origin="vault", data={"kind": "created"})
    first = store.status().first_memory_at

    publish_event(bus, "memory.entry.created", origin="vault", data={"kind": "created"})
    second = store.status().first_memory_at

    assert first == second


def test_unsubscribe_stops_tracking(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    unsubscribe = wire_funnel_tracking(bus, store)

    unsubscribe()
    publish_event(bus, "memory.vault.created", origin="dashboard", data={})

    assert store.status().vault_created_at is None
