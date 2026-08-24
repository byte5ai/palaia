from __future__ import annotations

import pytest

from palaia_hub.events.bridge import bridge_vault_events, to_envelope_args
from palaia_hub.events.bus import EventBus
from palaia_hub.events.schema import Envelope
from palaia_hub.vault.events import (
    EntityRenamed,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
)
from palaia_hub.vault.events import (
    EventBus as VaultEventBus,
)


@pytest.mark.parametrize(
    ("change_event", "expected_name"),
    [
        (
            NoteCreated(vault="work", path="a.md", permalink="a", checksum="c1"),
            "memory.entry.created",
        ),
        (
            NoteModified(vault="work", path="a.md", permalink="a", checksum="c2"),
            "memory.entry.updated",
        ),
        (
            NoteMoved(
                vault="work", path="b.md", previous_path="a.md", permalink="a", checksum="c1"
            ),
            "memory.entry.moved",
        ),
        (NoteDeleted(vault="work", path="a.md", permalink="a"), "memory.entry.deleted"),
        (
            EntityRenamed(vault="work", path="a.md", permalink="a", previous_permalink="old"),
            "memory.entry.updated",
        ),
    ],
)
def test_every_change_kind_maps_to_exactly_one_public_event_name(
    change_event: object, expected_name: str
) -> None:
    name, data = to_envelope_args(change_event)  # type: ignore[arg-type]

    assert name == expected_name
    assert data["kind"] == change_event.kind  # type: ignore[attr-defined]


def test_note_created_data_carries_path_and_checksum() -> None:
    event = NoteCreated(vault="work", path="a.md", permalink="a", checksum="c1")

    _, data = to_envelope_args(event)

    assert data["path"] == "a.md"
    assert data["checksum"] == "c1"
    assert data["external"] is False


def test_note_moved_data_carries_both_paths() -> None:
    event = NoteMoved(
        vault="work", path="b.md", previous_path="a.md", permalink="a", checksum="c1"
    )

    _, data = to_envelope_args(event)

    assert data["path"] == "b.md"
    assert data["previous_path"] == "a.md"


@pytest.mark.anyio
async def test_bridge_vault_events_forwards_to_the_hub_bus() -> None:
    vault_bus = VaultEventBus()
    hub_bus = EventBus()
    received: list[Envelope] = []
    hub_bus.on(received.append)

    bridge_vault_events(vault_bus, hub_bus)
    await vault_bus.publish(
        NoteCreated(vault="work", path="a.md", permalink="a", checksum="c1")
    )

    assert len(received) == 1
    envelope = received[0]
    assert envelope.event == "memory.entry.created"
    assert envelope.vault == "work"
    assert envelope.permalink == "a"
    assert envelope.origin == "vault"


@pytest.mark.anyio
async def test_unsubscribing_the_bridge_stops_forwarding() -> None:
    vault_bus = VaultEventBus()
    hub_bus = EventBus()
    received: list[Envelope] = []
    hub_bus.on(received.append)

    unsubscribe = bridge_vault_events(vault_bus, hub_bus)
    unsubscribe()
    await vault_bus.publish(NoteDeleted(vault="work", path="a.md", permalink="a"))

    assert received == []
