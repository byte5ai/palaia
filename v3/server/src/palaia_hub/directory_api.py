"""``/api/directory`` REST mirror of the session directory (SPEC-402
deliverable #4), for the dashboard (SPEC-405 builds the screen) and any
other non-MCP caller.

**List/query are read-only for everyone.** Every ordinary mutation
(register, heartbeat, update, deregister) still comes from the sessions
themselves, over MCP, holding their own session secret — nothing here can
act *as* a session, which is exactly the point of the secret (see
:mod:`palaia_hub.directory.store`'s module docstring).

**One owner control lives here, deliberately.** ``POST /{handle}/
deregister`` is SPEC-405 deliverable #2's "deregister a stale session" —
the one directory mutation the *owner* may make without holding that
session's secret, because this route is not "act as a session", it is "act
as the owner, on a session". ``/api/*`` already sits behind
:mod:`palaia_hub.admin_session`'s sign-in-and-CSRF gate wherever the hub's
mode requires one, which is what makes that safe: MASTERPLAN §5.4 trust
rule #7, "the human can read along, join in, or shut a conversation down"
— this is the directory's half of "shut down" (the messenger's half,
ending a conversation, is the equivalent route in
:mod:`palaia_hub.messenger_api`). Every *other* route here stays read-only,
on purpose — this is the one, named exception, not a precedent for adding
more without the same trust-rule citation.
"""

from __future__ import annotations

from fastapi import APIRouter

from .directory.models import DeregisterResult, ListResult, QueryResult, SessionStatus
from .directory.service import DirectoryService


def build_directory_router(service: DirectoryService) -> APIRouter:
    router = APIRouter(prefix="/api/directory", tags=["directory"])

    @router.get("/", response_model=ListResult)
    async def list_sessions(
        status: SessionStatus | None = None,
        platform: str | None = None,
        capability: str | None = None,
    ) -> ListResult:
        return await service.list(status=status, platform=platform, capability=capability)

    @router.get("/query", response_model=QueryResult)
    async def query_sessions(
        scope_contains: str | None = None, capability: str | None = None
    ) -> QueryResult:
        return await service.query(scope_contains=scope_contains, capability=capability)

    @router.post("/{handle}/deregister", response_model=DeregisterResult)
    async def deregister_session(handle: str) -> DeregisterResult:
        """Owner control (SPEC-405 deliverable #2): remove ``handle`` from
        the directory without its session secret. Idempotent — an
        already-gone handle answers ``deregistered=false``, not a 404, the
        same shape the MCP tool's own ``directory_deregister`` uses."""
        return await service.admin_deregister(handle)

    return router


__all__ = ["build_directory_router"]
