"""The public event bus (SPEC-201) — schema, transport, and the vault bridge.

See ``v3/docs/events.md`` for the envelope contract this package implements.
"""

from __future__ import annotations

from .bridge import bridge_vault_events, to_envelope_args
from .bus import (
    DEFAULT_HEALTH_INTERVAL_SECONDS,
    HEALTH_INTERVAL_ENV,
    EventBus,
    HealthSnapshot,
    Subscriber,
    build_events_router,
    publish_event,
    publish_from_hook,
    start_background_tasks,
    stop_background_tasks,
)
from .schema import KNOWN_EVENT_NAMES, SCHEMA_VERSION, Envelope, EventName, HubEventHook

__all__ = [
    "DEFAULT_HEALTH_INTERVAL_SECONDS",
    "HEALTH_INTERVAL_ENV",
    "KNOWN_EVENT_NAMES",
    "SCHEMA_VERSION",
    "Envelope",
    "EventBus",
    "EventName",
    "HealthSnapshot",
    "HubEventHook",
    "Subscriber",
    "bridge_vault_events",
    "build_events_router",
    "publish_event",
    "publish_from_hook",
    "start_background_tasks",
    "stop_background_tasks",
    "to_envelope_args",
]
