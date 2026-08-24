"""``/api/market/*`` REST surface (SPEC-303 deliverable #4)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from palaia_hub.market.api import build_market_router
from palaia_hub.market.curated import CuratedIndexClient
from palaia_hub.market.manual import ManualEntryStore
from palaia_hub.market.service import MarketService
from palaia_hub.registry.client import RegistryClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _empty_registry_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v0/servers":
        return httpx.Response(200, json={"servers": []})
    return httpx.Response(404)


def _offline_curated_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("offline in this test")


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    registry_client = RegistryClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_empty_registry_handler)),
        cache_dir=tmp_path / "registry_cache",
    )
    curated_client = CuratedIndexClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_offline_curated_handler)),
        last_good_path=tmp_path / "last_good.json",
    )
    manual_store = ManualEntryStore(tmp_path / "manual.sqlite3")
    service = MarketService(
        registry_client=registry_client, curated_client=curated_client, manual_store=manual_store
    )
    fastapi_app = FastAPI()
    fastapi_app.include_router(build_market_router(service))
    return fastapi_app


@pytest.mark.anyio
async def test_search_endpoint_returns_the_merged_shape(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/api/market/search")

    assert response.status_code == 200
    body = response.json()
    assert "entries" in body and "stale" in body and "notes" in body


@pytest.mark.anyio
async def test_creating_and_fetching_a_manual_entry(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        create = await http.post(
            "/api/market/manual",
            json={
                "id": "manual.api-test",
                "name": "API Test Tool",
                "one_liner": "Created through the REST endpoint.",
                "kind": "remote",
                "source": {"type": "url", "value": "https://example.com/mcp"},
                "maintainer": "tester",
            },
        )
        assert create.status_code == 201
        assert create.json()["verified"] is False
        assert create.json()["provenance"] == "manual"

        fetched = await http.get("/api/market/entry/manual.api-test")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == "manual.api-test"


@pytest.mark.anyio
async def test_duplicate_manual_entry_is_a_409(app: FastAPI) -> None:
    payload = {
        "id": "manual.dup",
        "name": "Dup",
        "one_liner": "x",
        "kind": "remote",
        "source": {"type": "url", "value": "https://example.com/mcp"},
        "maintainer": "tester",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        first = await http.post("/api/market/manual", json=payload)
        assert first.status_code == 201
        second = await http.post("/api/market/manual", json=payload)
        assert second.status_code == 409


@pytest.mark.anyio
async def test_unknown_entry_is_a_404(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/api/market/entry/does-not-exist")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_offline_curated_search_reports_stale_and_a_note(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as http:
        response = await http.get("/api/market/search", params={"source": "curated"})

    body = response.json()
    assert body["stale"] is True
    assert "curated" in body["notes"]
