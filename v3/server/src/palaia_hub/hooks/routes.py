"""REST surface for webhook management (SPEC-201 deliverable #3).

Mounted at ``/api/hooks`` by :func:`palaia_hub.app.create_app` when it is
given a ``hook_store`` — opt-in, same posture as ``/api/auth/tokens``
(see :mod:`palaia_hub.auth.routes`'s module docstring): no per-request auth
of its own, protected by the operating mode's network topology rather than
a dashboard login.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import CreatedHook, DeadLetter, HookInfo
from .outbox import HookOutbox
from .store import HookError, HookStore


class CreateHookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    events: list[str] = Field(default_factory=lambda: ["*"])


class SetEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def build_hooks_router(store: HookStore, outbox: HookOutbox) -> APIRouter:
    """Build the ``/api/hooks`` router, backed by ``store`` and ``outbox``."""
    router = APIRouter(prefix="/api/hooks", tags=["hooks"])

    @router.post("", response_model=CreatedHook)
    async def create_hook(body: CreateHookRequest) -> CreatedHook:
        try:
            return store.create(body.url, body.events)
        except HookError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("", response_model=list[HookInfo])
    async def list_hooks() -> list[HookInfo]:
        return store.list_info()

    @router.patch("/{hook_id}", response_model=HookInfo)
    async def set_enabled(hook_id: str, body: SetEnabledRequest) -> HookInfo:
        try:
            return store.set_enabled(hook_id, body.enabled)
        except HookError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/{hook_id}", status_code=204)
    async def delete_hook(hook_id: str) -> None:
        try:
            store.delete(hook_id)
        except HookError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{hook_id}/dead_letters", response_model=list[DeadLetter])
    async def dead_letters(hook_id: str) -> list[DeadLetter]:
        if store.get(hook_id) is None:
            raise HTTPException(status_code=404, detail=f"no hook with id {hook_id!r}")
        return [
            DeadLetter(
                id=row.id,
                hook_id=row.hook_id,
                event_id=row.event_id,
                event_name=row.event_name,
                attempts=row.attempts,
                last_error=row.last_error,
                created_at=row.created_at,
            )
            for row in outbox.list_dead_letters(hook_id)
        ]

    return router


__all__ = ["build_hooks_router"]
