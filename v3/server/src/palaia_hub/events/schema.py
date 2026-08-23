"""The public event envelope (SPEC-201) — one schema, three consumers.

Every palaia subsystem that wants to tell the outside world "something
happened" emits one of these. The in-process subscription API
(:class:`~palaia_hub.events.bus.EventBus`), the ``/api/events`` SSE stream,
and outbound webhooks all carry exactly this shape — see
``v3/docs/events.md`` for the full contract and the additive-evolution
rule this module's ``SCHEMA_VERSION`` anchors.

Envelope shape (MASTERPLAN §5.6 / SPEC-201 deliverable #1)::

    {event, ts, vault?, permalink?, origin, data, id, schema_version}

``event`` and ``data`` carry the payload; ``id`` is this event's stable
idempotency key (a webhook receiver that sees the same ``id`` twice knows
it is the same delivery retried, not a new occurrence); ``vault``/
``permalink`` are populated whenever the event concerns one specific vault
entry, ``None`` otherwise (e.g. ``hub.started``).
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal, get_args

#: Bumped only on a breaking change to the *envelope* shape itself (a field
#: renamed or removed). Adding a new event name, a new optional envelope
#: field, or a new key inside ``data`` is additive and does NOT bump this —
#: see docs/events.md "Evolution rule". A consumer must ignore any field or
#: event name it does not recognize rather than fail closed.
SCHEMA_VERSION = 1

#: The v1 event vocabulary (SPEC-201 deliverable #1), plus ``health`` — the
#: SPEC-109 dashboard heartbeat, carried over unchanged as an additive,
#: hub-internal event so the existing "connection alive" indicator keeps
#: working on the same one bus rather than a second parallel mechanism.
EventName = Literal[
    "hub.started",
    "client.connected",
    "memory.entry.created",
    "memory.entry.updated",
    "memory.entry.deleted",
    "memory.entry.moved",
    "inbox.captured",
    "index.reindexed",
    "index.embed_backlog_drained",
    "doctor.finding",
    "stash.set",
    "stash.get",
    "stash.del",
    "stash.evicted",
    "health",
]

KNOWN_EVENT_NAMES: frozenset[str] = frozenset(get_args(EventName))


@dataclasses.dataclass(frozen=True, slots=True)
class Envelope:
    """One item on the public event bus."""

    event: str
    data: dict[str, Any]
    origin: str
    vault: str | None = None
    permalink: str | None = None
    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = dataclasses.field(default_factory=time.time)
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        """The wire shape: every consumer (SSE, webhook, in-process) sees this."""
        return {
            "event": self.event,
            "ts": self.ts,
            "vault": self.vault,
            "permalink": self.permalink,
            "origin": self.origin,
            "data": self.data,
            "id": self.id,
            "schema_version": self.schema_version,
        }

    def to_sse(self) -> str:
        """Render as one Server-Sent Events frame.

        The SSE ``event:`` field carries the same dotted name the envelope's
        own ``event`` field does — one name, everywhere — so a browser
        ``EventSource.addEventListener(envelope.event, ...)`` and a
        webhook/in-process subscriber are looking at the same string.
        """
        payload = json.dumps(self.to_json())
        return f"id: {self.id}\nevent: {self.event}\ndata: {payload}\n\n"


#: A producer that cannot reach the hub's :class:`~palaia_hub.events.bus.EventBus`
#: directly (the vault engine, the index, the inbox — packages that must not
#: depend on the hub's transport layer, see their own module docstrings)
#: reports through this narrower shape instead: an event name plus a data
#: dict that MAY carry a ``"vault"`` and/or ``"permalink"`` key, promoted to
#: the envelope's own fields by whichever wiring code owns the real bus
#: (see :func:`palaia_hub.events.bus.publish_from_hook`).
HubEventHook = Callable[[str, dict[str, Any]], None]

__all__ = [
    "KNOWN_EVENT_NAMES",
    "SCHEMA_VERSION",
    "Envelope",
    "EventName",
    "HubEventHook",
]
