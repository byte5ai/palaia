"""Issue #353: outbound response caps are enforced while the body is read.

The registry client, the curated index and the update check all cap the
size of what they fetch — but each read the whole body first and compared
its length afterwards, so a hostile or broken host could make the hub
buffer gigabytes before rejecting them. :func:`get_bounded` refuses a
``Content-Length`` over the cap before reading a byte, and abandons a
stream the moment the received count crosses it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from palaia_hub.market.curated import CuratedIndexClient, _FetchFailure
from palaia_hub.registry.client import RegistryClient, RegistryOfflineError
from palaia_hub.security.bounded_fetch import ResponseTooLargeError, get_bounded
from palaia_hub.update import _CheckFailed, _get_registry_json

pytestmark = pytest.mark.anyio

CHUNK = b"x" * 1024


class _EndlessStream(httpx.AsyncByteStream):
    """A body that keeps coming — and counts how much of it was actually read."""

    def __init__(self, chunks: int) -> None:
        self.chunks = chunks
        self.served = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.chunks):
            self.served += len(CHUNK)
            yield CHUNK


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_a_body_over_the_cap_is_abandoned_not_buffered() -> None:
    stream = _EndlessStream(chunks=1000)  # ~1 MB on offer

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        with pytest.raises(ResponseTooLargeError, match="too large"):
            await get_bounded(http, "https://host.test/big", max_bytes=10 * 1024)

    # Reading stopped as soon as the cap was crossed: one chunk past it,
    # not the megabyte the host had to offer.
    assert stream.served <= 11 * 1024


async def test_a_declared_length_over_the_cap_is_refused_before_any_byte() -> None:
    stream = _EndlessStream(chunks=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": str(1000 * 1024)}, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        with pytest.raises(ResponseTooLargeError, match="declares"):
            await get_bounded(http, "https://host.test/big", max_bytes=1024)

    assert stream.served == 0


async def test_a_body_within_the_cap_comes_back_whole() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with _client(httpx.MockTransport(handler)) as http:
        response = await get_bounded(http, "https://host.test/small", max_bytes=1024)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_an_error_status_is_returned_without_reading_its_body() -> None:
    stream = _EndlessStream(chunks=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        response = await get_bounded(http, "https://host.test/down", max_bytes=1024)

    assert response.status_code == 503
    assert response.content == b""
    assert stream.served == 0


# ------------------------------------------------- the three callers use it


async def test_the_registry_client_stops_reading_an_oversized_page(tmp_path: Path) -> None:
    stream = _EndlessStream(chunks=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        client = RegistryClient(client=http, cache_dir=tmp_path, max_bytes=4096)
        with pytest.raises(RegistryOfflineError, match="too large"):
            await client.search("anything")
    assert stream.served <= 5 * 1024


async def test_the_curated_index_stops_reading_an_oversized_document(tmp_path: Path) -> None:
    stream = _EndlessStream(chunks=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http, last_good_path=tmp_path / "last_good.json", max_bytes=4096
        )
        with pytest.raises(_FetchFailure, match="too large"):
            await client._download()
    assert stream.served <= 5 * 1024


async def test_the_update_check_stops_reading_an_oversized_manifest() -> None:
    stream = _EndlessStream(chunks=1000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async with _client(httpx.MockTransport(handler)) as http:
        with pytest.raises(_CheckFailed, match="manifest response too large"):
            await _get_registry_json(
                http,
                "https://registry.test/v2/x/manifests/latest",
                what="manifest",
                not_found="no such tag",
                timeout_seconds=5.0,
                max_bytes=4096,
            )
    assert stream.served <= 5 * 1024
