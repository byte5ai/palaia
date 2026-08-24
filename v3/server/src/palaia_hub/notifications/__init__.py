"""The dashboard notification center (SPEC-307 deliverable #1).

No email/push channel in v1 — see that SPEC's Non-goals. A small, durable
SQLite-backed log (:mod:`.store`) plus a REST surface (:mod:`.routes`); the
``notification`` automation action kind (:mod:`palaia_hub.automations`) is
its only writer today.
"""

from __future__ import annotations

from .models import NotificationRecord
from .routes import build_notifications_router
from .store import MAX_NOTIFICATIONS, NOTIFICATIONS_RELATIVE_PATH, NotificationStore

__all__ = [
    "MAX_NOTIFICATIONS",
    "NOTIFICATIONS_RELATIVE_PATH",
    "NotificationRecord",
    "NotificationStore",
    "build_notifications_router",
]
