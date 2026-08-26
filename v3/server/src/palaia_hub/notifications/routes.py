"""REST surface for the notification center (SPEC-307 deliverable #1).

Mounted at ``/api/notifications`` by :func:`palaia_hub.app.create_app` when
given a ``notification_store`` — same opt-in posture as ``/api/hooks``: no
per-request auth of its own, protected by the operating mode's network
topology.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import NotificationRecord
from .store import NotificationStore


def build_notifications_router(store: NotificationStore) -> APIRouter:
    router = APIRouter(prefix="/api/notifications", tags=["notifications"])

    @router.get("", response_model=list[NotificationRecord])
    async def list_notifications(unread_only: bool = False) -> list[NotificationRecord]:
        return store.list(unread_only=unread_only)

    @router.get("/unread_count")
    async def unread_count() -> dict[str, int]:
        return {"count": store.unread_count()}

    @router.post("/{notification_id}/read", response_model=NotificationRecord)
    async def mark_read(notification_id: int) -> NotificationRecord:
        record = store.mark_read(notification_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"no notification with id {notification_id!r}"
            )
        return record

    @router.post("/read_all")
    async def mark_all_read() -> dict[str, str]:
        store.mark_all_read()
        return {"status": "ok"}

    return router


__all__ = ["build_notifications_router"]
