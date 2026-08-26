"""Bridges the vault engine's typed change events onto the public bus.

:mod:`palaia_hub.vault.events` is the *internal* vocabulary — the vault
engine, the index (SPEC-104) and the watcher pattern-match on
``NoteCreated``/``NoteModified``/... directly, and that stays true; this
SPEC does not ask those consumers to be rewired onto the public envelope.
What changes is that the vault registry's bus (shared across every vault it
opens) is now also bridged here, one time, onto the hub's public
:class:`~palaia_hub.events.bus.EventBus` — so a note write anywhere produces
exactly one additional, public ``memory.entry.*`` event, and the SSE stream
and the webhook dispatcher both observe it (SPEC-201 acceptance: "SSE and
webhook consumers observe the same event for the same write").
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..vault.events import (
    ChangeEvent,
    EntityRenamed,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
)
from ..vault.events import (
    EventBus as VaultEventBus,
)
from .bus import EventBus, publish_event
from .schema import EventName

# Every internal ChangeEvent maps to exactly one public event name — no
# change kind is silently dropped, and none maps to more than one name, so
# a webhook filter on "memory.entry.updated" sees every rename too (a
# rename modifies an existing entry's identity; it does not create or
# delete one).
_EVENT_NAME: dict[type[ChangeEvent], EventName] = {
    NoteCreated: "memory.entry.created",
    NoteModified: "memory.entry.updated",
    NoteMoved: "memory.entry.moved",
    NoteDeleted: "memory.entry.deleted",
    EntityRenamed: "memory.entry.updated",
}


def _to_public_data(event: ChangeEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": event.kind, "external": event.external}
    for field in ("path", "previous_path", "checksum", "previous_checksum"):
        value = getattr(event, field, None)
        if value is not None:
            data[field] = value
    if isinstance(event, EntityRenamed):
        data["previous_permalink"] = event.previous_permalink
        data["title"] = event.title
        data["previous_title"] = event.previous_title
        data["rewritten_links"] = event.rewritten_links
    return data


def to_envelope_args(event: ChangeEvent) -> tuple[EventName, dict[str, Any]]:
    """The public event name + data ``bridge_vault_events`` would publish for ``event``."""
    return _EVENT_NAME[type(event)], _to_public_data(event)


def bridge_vault_events(vault_bus: VaultEventBus, hub_bus: EventBus) -> Callable[[], None]:
    """Subscribe ``vault_bus`` so every change on it also reaches ``hub_bus``.

    Returns the unsubscribe callable :meth:`VaultEventBus.subscribe` handed
    back, so the caller can tear the bridge down on shutdown.
    """

    async def _on_change(event: ChangeEvent) -> None:
        name, data = to_envelope_args(event)
        publish_event(
            hub_bus,
            name,
            origin="vault",
            vault=event.vault,
            permalink=event.permalink,
            data=data,
        )

    return vault_bus.subscribe(_on_change)


__all__ = ["bridge_vault_events", "to_envelope_args"]
