"""``/api/stash`` REST mirror of the stash tool family (SPEC-202 deliverable
#3), for jobs/dashboard callers that are not an MCP client. Same
:class:`~palaia_hub.stash.service.StashService` backs both surfaces, so a
value written through one is visible through the other immediately.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .stash.models import DelResult, GetResult, ListResult, SetResult, StashError, StatusResult
from .stash.service import StashService


class SetBody(BaseModel):
    value: Any
    ttl_seconds: float | None = None
    stale_after_seconds: float | None = None


def build_stash_router(service: StashService) -> APIRouter:
    router = APIRouter(prefix="/api/stash", tags=["stash"])

    @router.put("/{namespace}/{key}", response_model=SetResult)
    async def set_entry(namespace: str, key: str, body: SetBody) -> SetResult:
        try:
            return await service.set(
                namespace,
                key,
                body.value,
                ttl_seconds=body.ttl_seconds,
                stale_after_seconds=body.stale_after_seconds,
            )
        except StashError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{namespace}/{key}", response_model=GetResult)
    async def get_entry(namespace: str, key: str) -> GetResult:
        return await service.get(namespace, key)

    @router.delete("/{namespace}/{key}", response_model=DelResult)
    async def delete_entry(namespace: str, key: str) -> DelResult:
        return await service.delete(namespace, key)

    @router.get("/{namespace}", response_model=ListResult)
    async def list_entries(namespace: str) -> ListResult:
        return await service.list(namespace)

    @router.get("/", response_model=StatusResult)
    async def status() -> StatusResult:
        return await service.status()

    return router


__all__ = ["SetBody", "build_stash_router"]
