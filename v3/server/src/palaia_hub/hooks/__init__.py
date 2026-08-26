"""Outbound webhooks (SPEC-201): config, durable outbox, signed delivery.

See ``v3/docs/events.md`` for the event schema every delivery's body
carries, and this package's ``store``/``outbox``/``delivery``/``routes``
modules for how a hook is configured, queued, signed, and retried.
"""

from __future__ import annotations

from .delivery import DEFAULT_MAX_ATTEMPTS, HookDispatcher
from .models import CreatedHook, DeadLetter, HookInfo, HookRecord
from .outbox import OUTBOX_RELATIVE_PATH, HookOutbox, OutboxRow
from .routes import build_hooks_router
from .signing import sign, verify
from .store import HOOKS_FILE, HookError, HookStore

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "HOOKS_FILE",
    "OUTBOX_RELATIVE_PATH",
    "CreatedHook",
    "DeadLetter",
    "HookDispatcher",
    "HookError",
    "HookInfo",
    "HookOutbox",
    "HookRecord",
    "HookStore",
    "OutboxRow",
    "build_hooks_router",
    "sign",
    "verify",
]
