from __future__ import annotations

import httpx
import pytest

from palaia_hub.modes.selftest import check_public_url


def _client(handler: httpx.MockTransport | None = None, **kwargs: object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, **kwargs)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_a_reachable_hub_reports_reachable_with_latency() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/info"
        return httpx.Response(200, json={"mode": "cloud"})

    client = _client(httpx.MockTransport(handler))
    async with client:
        result = await check_public_url("https://hub.example.com", client=client)

    assert result.reachable is True
    assert result.status_code == 200
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.error == ""
    assert result.checked_url == "https://hub.example.com/api/info"


@pytest.mark.anyio
async def test_a_trailing_slash_in_the_public_url_does_not_double_up() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = _client(httpx.MockTransport(handler))
    async with client:
        result = await check_public_url("https://hub.example.com/", client=client)

    assert result.checked_url == "https://hub.example.com/api/info"


@pytest.mark.anyio
async def test_a_non_2xx_status_is_reported_as_unreachable_with_the_real_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    client = _client(httpx.MockTransport(handler))
    async with client:
        result = await check_public_url("https://hub.example.com", client=client)

    assert result.reachable is False
    assert result.status_code == 502
    assert "502" in result.error


@pytest.mark.anyio
async def test_a_connection_error_is_reported_honestly_not_as_a_generic_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(httpx.MockTransport(handler))
    async with client:
        result = await check_public_url("https://hub.example.com", client=client)

    assert result.reachable is False
    assert result.status_code is None
    assert "connection refused" in result.error


@pytest.mark.anyio
async def test_a_timeout_is_reported_as_a_timeout_not_as_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = _client(httpx.MockTransport(handler))
    async with client:
        result = await check_public_url("https://hub.example.com", client=client, timeout=2.0)

    assert result.reachable is False
    assert "timed out" in result.error
