"""Automations: the trigger -> condition -> action editor (SPEC-307).

MASTERPLAN §5.6's third step. SPEC-201 shipped hooks-as-config (the
``webhook`` action, still configured through its own screen and store,
:mod:`palaia_hub.hooks`); this package adds the three remaining action
kinds — ``memory_write``, ``stash_set``, ``notification`` — on the same
durable-outbox delivery discipline, plus the condition grammar and
templating that make an automation more than "receive every event".

Deliberately its own store/outbox rather than folded into
:mod:`palaia_hub.hooks`: a webhook's delivery carries an HMAC signature and
a secret that must never be logged (see ``HookRecord``'s docstring); none
of the three action kinds here has anything to sign or hide, and unifying
the two into one schema would mean either bolting a meaningless "secret"
field onto memory_write/stash_set/notification, or splitting the discriminator
back out one layer up — no simpler than two small, parallel packages.
"""

from __future__ import annotations

from .dispatcher import ActionError, AutomationDispatcher
from .models import (
    Action,
    AutomationInfo,
    AutomationRecord,
    ConditionClause,
    DeliveryLogEntry,
    MemoryWriteAction,
    NotificationAction,
    StashSetAction,
)
from .outbox import OUTBOX_RELATIVE_PATH, AutomationOutbox
from .routes import build_automations_router
from .store import AutomationError, AutomationStore

__all__ = [
    "OUTBOX_RELATIVE_PATH",
    "Action",
    "ActionError",
    "AutomationDispatcher",
    "AutomationError",
    "AutomationInfo",
    "AutomationOutbox",
    "AutomationRecord",
    "AutomationStore",
    "ConditionClause",
    "DeliveryLogEntry",
    "MemoryWriteAction",
    "NotificationAction",
    "StashSetAction",
    "build_automations_router",
]
