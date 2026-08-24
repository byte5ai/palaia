"""SPEC-303 acceptance: registry search/detail against a mocked v0.1 API;
offline behavior returns cached results marked stale; no request hangs
past its timeout."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from palaia_hub.registry.client import RegistryClient, RegistryOfflineError

_SERVERS_PAGE = {
    "servers": [
        {
            "server": {
                "name": "io.example/weather",
                "description": "A weather MCP server.",
                "version": "1.0.0",
                "remotes": [{"url": "https://weather.example.com/mcp"}],
            },
            "_meta": {"io.modelcontextprotocol.registry/official": {"id": "weather-123"}},
        }
    ]
}

_DETAIL_PAGE = {
    "server": {
        "name": "io.example/weather",
        "description": "A weather MCP server.",
        "version": "1.0.0",
        "remotes": [{"url": "https://weather.example.com/mcp"}],
    },
    "_meta": {"io.modelcontextprotocol.registry/official": {"id": "weather-123"}},
}


def _client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.anyio
async def test_search_returns_mapped_servers_fresh_and_not_stale(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/servers"
        return httpx.Response(200, json=_SERVERS_PAGE)

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path)
        result = await client.search("weather")

    assert result.stale is False
    assert result.offline is False
    assert len(result.servers) == 1
    assert result.servers[0].id == "weather-123"
    assert result.servers[0].name == "io.example/weather"


@pytest.mark.anyio
async def test_detail_returns_the_single_server(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/servers/weather-123"
        return httpx.Response(200, json=_DETAIL_PAGE)

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path)
        server = await client.detail("weather-123")

    assert server is not None
    assert server.id == "weather-123"


@pytest.mark.anyio
async def test_detail_404_is_a_clean_none_not_a_fallback(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path)
        server = await client.detail("does-not-exist")

    assert server is None


@pytest.mark.anyio
async def test_a_fresh_within_ttl_cache_hit_needs_no_network_round_trip(tmp_path: Path) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=_SERVERS_PAGE)

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path, ttl_seconds=3600)
        await client.search("weather")
        result = await client.search("weather")

    assert calls["count"] == 1
    assert result.stale is False


@pytest.mark.anyio
async def test_offline_after_a_successful_fetch_serves_the_cache_marked_stale(
    tmp_path: Path,
) -> None:
    state = {"online": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["online"]:
            return httpx.Response(200, json=_SERVERS_PAGE)
        raise httpx.ConnectError("connection refused")

    async with _client_for(httpx.MockTransport(handler)) as http:
        # ttl_seconds=0 forces every call to attempt a fresh network fetch.
        client = RegistryClient(client=http, cache_dir=tmp_path, ttl_seconds=0)
        first = await client.search("weather")
        assert first.stale is False

        state["online"] = False
        second = await client.search("weather")

    assert second.stale is True
    assert second.offline is True
    assert len(second.servers) == 1
    assert "connection" in second.note.lower() or "network" in second.note.lower()


@pytest.mark.anyio
async def test_offline_with_no_cache_at_all_raises_a_named_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path)
        with pytest.raises(RegistryOfflineError):
            await client.search("weather")


@pytest.mark.anyio
async def test_a_timeout_never_hangs_and_falls_back_to_cache(tmp_path: Path) -> None:
    state = {"first": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["first"]:
            state["first"] = False
            return httpx.Response(200, json=_SERVERS_PAGE)
        raise httpx.ReadTimeout("timed out")

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path, ttl_seconds=0, timeout_seconds=1.0)
        await client.search("weather")
        result = await client.search("weather")

    assert result.stale is True
    assert "timed out" in result.note.lower()


@pytest.mark.anyio
async def test_an_oversized_response_is_rejected_like_a_failed_fetch(tmp_path: Path) -> None:
    huge_page = {"servers": [_SERVERS_PAGE["servers"][0]] * 1}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=huge_page)

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path, max_bytes=10)
        with pytest.raises(RegistryOfflineError):
            await client.search("weather")
