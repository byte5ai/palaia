"""Notification data shapes (SPEC-307 deliverable #1's ``notification``
action kind): a small dashboard notification center, no email/push in v1.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NotificationRecord(BaseModel):
    """One entry in the notification center."""

    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    body: str
    source: str
    created_at: str
    read: bool


__all__ = ["NotificationRecord"]
