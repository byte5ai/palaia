"""``/api/market`` — the merged marketplace REST surface (SPEC-303
deliverable #4): the one place the dashboard (SPEC-304) reads add-ons
from, regardless of which of the three sources produced them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .manual import ManualEntryError
from .models import ManualEntryCreate, MarketEntry, Provenance
from .service import MarketService


class SearchResponse(BaseModel):
    entries: list[MarketEntry]
    stale: bool
    notes: dict[str, str]


def build_market_router(service: MarketService) -> APIRouter:
    router = APIRouter(prefix="/api/market", tags=["market"])

    @router.get("/search", response_model=SearchResponse)
    async def search(q: str = "", source: Provenance | None = None) -> SearchResponse:
        result = await service.search(q, source=source)
        return SearchResponse(entries=list(result.entries), stale=result.stale, notes=result.notes)

    @router.get("/entry/{entry_id}", response_model=MarketEntry)
    async def get_entry(entry_id: str) -> MarketEntry:
        entry = await service.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no marketplace entry {entry_id!r}")
        return entry

    @router.post("/manual", response_model=MarketEntry, status_code=201)
    async def create_manual_entry(payload: ManualEntryCreate) -> MarketEntry:
        try:
            return service.add_manual_entry(payload)
        except ManualEntryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/curated/refresh", status_code=202)
    async def refresh_curated_index() -> dict[str, Any]:
        await service.refresh_curated_index()
        return {"status": "refreshed"}

    return router


__all__ = ["SearchResponse", "build_market_router"]
