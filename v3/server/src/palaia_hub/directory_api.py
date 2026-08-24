"""``/api/directory`` REST mirror of the session directory (SPEC-402
deliverable #4), for the dashboard (SPEC-405 builds the screen) and any
other non-MCP caller. **List/query only** — mutations (register, heartbeat,
update, deregister) come from the sessions themselves, over MCP, holding
their own session secret; nothing here can act on a session's behalf, which
is exactly the point of the secret (see
:mod:`palaia_hub.directory.store`'s module docstring).
"""

from __future__ import annotations

from fastapi import APIRouter

from .directory.models import ListResult, QueryResult, SessionStatus
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

    return router


__all__ = ["build_directory_router"]
