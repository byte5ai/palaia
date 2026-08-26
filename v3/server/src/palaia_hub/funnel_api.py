"""``GET /api/funnel/status`` — the dashboard hub-status surface's read side
of :mod:`palaia_hub.funnel` (SPEC-504 deliverable #3).

Always mounted, the same posture as ``/api/health``/``/api/info``
(:mod:`palaia_hub.app`): every hub has a funnel store from the moment it
first boots, whether or not a vault exists yet, so there is nothing to
opt into. Read-only by design — every timestamp behind this response comes
from a real server-side event (see the module docstring on
:mod:`palaia_hub.funnel`), never from anything a request body could set,
so there is no way for a client to fabricate its own "set up in 4m12s."
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .funnel import FunnelStore


class FunnelStatusOut(BaseModel):
    """The wizard-step timestamps plus the derived time-to-first-memory.

    Every ``*_at`` field is a Unix timestamp (seconds) or ``null`` when
    that step has not happened yet on this hub. ``time_to_first_memory_
    seconds``/``_display`` are ``null`` until both ``hub_started_at`` and
    ``first_memory_at`` are set.
    """

    model_config = ConfigDict(extra="forbid")

    hub_started_at: float | None
    vault_created_at: float | None
    client_connected_at: float | None
    first_memory_at: float | None
    time_to_first_memory_seconds: float | None
    time_to_first_memory_display: str | None


def build_funnel_router(store: FunnelStore) -> APIRouter:
    """Build the ``/api/funnel`` router bound to ``store``."""
    router = APIRouter(tags=["funnel"])

    @router.get("/api/funnel/status", response_model=FunnelStatusOut)
    async def funnel_status() -> FunnelStatusOut:
        status = store.status()
        return FunnelStatusOut(
            hub_started_at=status.hub_started_at,
            vault_created_at=status.vault_created_at,
            client_connected_at=status.client_connected_at,
            first_memory_at=status.first_memory_at,
            time_to_first_memory_seconds=status.time_to_first_memory_seconds,
            time_to_first_memory_display=status.time_to_first_memory_display,
        )

    return router


__all__ = ["FunnelStatusOut", "build_funnel_router"]
