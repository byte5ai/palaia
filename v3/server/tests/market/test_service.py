"""SPEC-303 acceptance: merged search returns all three sources in one
shape (contract test)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.market.curated import CuratedIndexClient
from palaia_hub.market.manual import ManualEntryStore
from palaia_hub.market.models import ManualEntryCreate, MarketEntry, SourceLocator
from palaia_hub.market.service import MarketService
from palaia_hub.registry.client import RegistryClient

from .conftest import dump, make_document

_REGISTRY_PAGE = {
    "servers": [
        {
            "server": {
                "name": "io.example/weather",
                "description": "A weather MCP server.",
                "remotes": [{"url": "https://weather.example.com/mcp"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"id": "weather-123"}},
        }
    ]
}


_REGISTRY_DETAIL = _REGISTRY_PAGE["servers"][0]


def _registry_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v0/servers":
        return httpx.Response(200, json=_REGISTRY_PAGE)
    if request.url.path == "/v0/servers/weather-123":
        return httpx.Response(200, json=_REGISTRY_DETAIL)
    return httpx.Response(404)


@pytest.fixture
def market_service(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> MarketService:
    _, public_key_b64 = keypair
    document = sign_document(make_document())

    def curated_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(document))

    registry_client = RegistryClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(_registry_handler)),
        cache_dir=tmp_path / "registry_cache",
    )
    curated_client = CuratedIndexClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(curated_handler)),
        public_key_b64=public_key_b64,
        last_good_path=tmp_path / "last_good.json",
    )
    manual_store = ManualEntryStore(tmp_path / "manual.sqlite3")
    manual_store.add(
        ManualEntryCreate(
            id="manual.one",
            name="Manual One",
            one_liner="Hand-typed entry.",
            kind="skill",
            source=SourceLocator(type="url", value="https://example.com/SKILL.md"),
            maintainer="someone",
        )
    )
    return MarketService(
        registry_client=registry_client, curated_client=curated_client, manual_store=manual_store
    )


@pytest.mark.anyio
async def test_merged_search_returns_all_three_sources_in_one_shape(
    market_service: MarketService,
) -> None:
    result = await market_service.search()

    by_provenance = {e.provenance: e for e in result.entries}
    assert set(by_provenance) == {"registry", "curated", "manual"}
    for entry in result.entries:
        # Every entry, regardless of source, is the same pydantic shape
        # with `source` (locator) and `verified` always present.
        assert isinstance(entry, MarketEntry)
        assert entry.source is not None
        assert isinstance(entry.verified, bool)

    assert by_provenance["registry"].verified is False
    assert by_provenance["curated"].verified is True
    assert by_provenance["manual"].verified is False
    assert by_provenance["manual"].provenance == "manual"


@pytest.mark.anyio
async def test_search_can_be_filtered_to_one_source(market_service: MarketService) -> None:
    result = await market_service.search(source="manual")

    assert len(result.entries) == 1
    assert result.entries[0].provenance == "manual"


@pytest.mark.anyio
async def test_search_query_filters_by_name_or_one_liner(market_service: MarketService) -> None:
    result = await market_service.search("weather")

    assert {e.id for e in result.entries} == {"weather-123"}


@pytest.mark.anyio
async def test_get_entry_finds_across_all_three_sources(market_service: MarketService) -> None:
    manual = await market_service.get_entry("manual.one")
    curated = await market_service.get_entry("acme.tool")
    registry = await market_service.get_entry("weather-123")
    missing = await market_service.get_entry("does-not-exist")

    assert manual is not None and manual.provenance == "manual"
    assert curated is not None and curated.provenance == "curated"
    assert registry is not None and registry.provenance == "registry"
    assert missing is None


@pytest.mark.anyio
async def test_refresh_curated_index_publishes_the_event(market_service: MarketService) -> None:
    published: list[tuple[str, dict]] = []
    market_service.publish = lambda event, data: published.append((event, data))

    await market_service.refresh_curated_index()

    assert len(published) == 1
    event, data = published[0]
    assert event == "market.index.updated"
    assert data["stale"] is False
    assert data["entry_count"] == 1
