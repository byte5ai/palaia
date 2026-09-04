"""SPEC-303 acceptance: a tampered curated index (bad signature, wrong
key, downgraded generated_at) is refused and the last good copy served,
with a WARNING naming the reason. Plus issue #321: the outcome of a fetch,
good or bad, is cached on disk so the URL is asked once per TTL, not once
per marketplace request."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.market.curated import CuratedIndexClient, canonical_bytes

from .conftest import dump, make_document, make_entry


def _client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.anyio
async def test_a_validly_signed_document_is_accepted_fresh(
    tmp_path: Path,
    keypair: tuple[Ed25519PrivateKey, str],
    sign_document: Callable[[dict], dict],
) -> None:
    _, public_key_b64 = keypair
    document = sign_document(make_document())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(document))

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http,
            public_key_b64=public_key_b64,
            last_good_path=tmp_path / "last_good.json",
        )
        result = await client.fetch()

    assert result.stale is False
    assert result.warning == ""
    assert len(result.entries) == 1
    assert result.entries[0].id == "acme.tool"
    assert result.entries[0].provenance == "curated"
    assert result.entries[0].verified is True


@pytest.mark.anyio
async def test_a_bad_signature_is_refused_and_falls_back(
    tmp_path: Path,
    keypair: tuple[Ed25519PrivateKey, str],
    sign_document: Callable[[dict], dict],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, public_key_b64 = keypair
    good = sign_document(make_document(generated_at="2026-08-01T00:00:00Z"))
    tampered = dict(good)
    tampered["entries"] = [make_entry("evil.tool")]  # payload changed, signature now stale

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(tampered))

    last_good_path = tmp_path / "last_good.json"
    last_good_path.write_text(json.dumps(good), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        async with _client_for(httpx.MockTransport(handler)) as http:
            client = CuratedIndexClient(
                client=http, public_key_b64=public_key_b64, last_good_path=last_good_path
            )
            result = await client.fetch()

    assert result.stale is True
    assert "signature" in result.warning.lower()
    assert result.entries[0].id == "acme.tool"  # the last GOOD copy, not the tampered one
    assert any("signature" in record.message.lower() for record in caplog.records)


@pytest.mark.anyio
async def test_a_document_signed_with_the_wrong_key_is_refused(
    tmp_path: Path, sign_document: Callable[[dict], dict]
) -> None:
    wrong_key = Ed25519PrivateKey.generate()
    wrong_public_b64 = base64.b64encode(wrong_key.public_key().public_bytes_raw()).decode()
    document = sign_document(make_document())  # signed with the *other* keypair fixture's key

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(document))

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http,
            public_key_b64=wrong_public_b64,
            last_good_path=tmp_path / "last_good.json",
        )
        result = await client.fetch()

    assert result.stale is True
    assert "signature" in result.warning.lower()
    assert result.entries == ()  # no last-good copy, and this key doesn't match the starter index


@pytest.mark.anyio
async def test_a_downgraded_generated_at_is_refused_as_a_rollback(
    tmp_path: Path,
    keypair: tuple[Ed25519PrivateKey, str],
    sign_document: Callable[[dict], dict],
) -> None:
    _, public_key_b64 = keypair
    newer = sign_document(make_document(generated_at="2026-08-20T00:00:00Z"))
    older = sign_document(make_document(generated_at="2026-08-01T00:00:00Z"))

    last_good_path = tmp_path / "last_good.json"
    last_good_path.write_text(json.dumps(newer), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(older))

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http, public_key_b64=public_key_b64, last_good_path=last_good_path
        )
        result = await client.fetch()

    assert result.stale is True
    assert "older" in result.warning.lower() or "rollback" in result.warning.lower()
    assert result.generated_at == "2026-08-20T00:00:00Z"  # still the newer, trusted copy


@pytest.mark.anyio
async def test_offline_falls_back_to_the_last_verified_copy(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    _, public_key_b64 = keypair
    good = sign_document(make_document())
    last_good_path = tmp_path / "last_good.json"
    last_good_path.write_text(json.dumps(good), encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network is unreachable")

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http, public_key_b64=public_key_b64, last_good_path=last_good_path
        )
        result = await client.fetch()

    assert result.stale is True
    assert "network" in result.warning.lower() or "unreachable" in result.warning.lower()
    assert len(result.entries) == 1


@pytest.mark.anyio
async def test_a_valid_document_is_written_as_the_new_last_good_copy(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    last_good_path = tmp_path / "last_good.json"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=dump(document))

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(
            client=http, public_key_b64=public_key_b64, last_good_path=last_good_path
        )
        await client.fetch()

    assert last_good_path.exists()
    on_disk = json.loads(last_good_path.read_text(encoding="utf-8"))
    assert on_disk["generated_at"] == document["generated_at"]


def test_canonical_bytes_ignores_the_signature_key_and_key_order() -> None:
    doc_a = {"a": 1, "b": 2, "signature": "x"}
    doc_b = {"signature": "y", "b": 2, "a": 1}
    assert canonical_bytes(doc_a) == canonical_bytes(doc_b)


# ------------------------------------------------- TTL cache (issue #321)


class _Clock:
    """A settable time source, so TTL expiry needs no sleeping."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _counting_handler(
    respond: Callable[[httpx.Request], httpx.Response],
) -> tuple[Callable[[httpx.Request], httpx.Response], dict[str, int]]:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return respond(request)

    return handler, calls


def _cached_client(
    http: httpx.AsyncClient, tmp_path: Path, public_key_b64: str, clock: _Clock, **kwargs: Any
) -> CuratedIndexClient:
    return CuratedIndexClient(
        client=http,
        public_key_b64=public_key_b64,
        last_good_path=tmp_path / "last_good.json",
        cache_dir=tmp_path / "market_curated_cache",
        clock=clock,
        **kwargs,
    )


@pytest.mark.anyio
async def test_a_verified_fetch_is_served_from_disk_within_the_ttl(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = _cached_client(http, tmp_path, public_key_b64, clock, ttl_seconds=3600)
        first = await client.fetch()
        clock.advance(3599)
        second = await client.fetch()

    assert calls["count"] == 1
    assert first.stale is False and second.stale is False
    assert second.entries == first.entries
    assert (tmp_path / "market_curated_cache").is_dir()


@pytest.mark.anyio
async def test_the_cache_survives_a_new_client_over_the_same_directory(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    """It is a *disk* cache: a hub restart (a fresh client) within the TTL
    still asks the network nothing."""
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        await _cached_client(http, tmp_path, public_key_b64, clock).fetch()
        result = await _cached_client(http, tmp_path, public_key_b64, clock).fetch()

    assert calls["count"] == 1
    assert result.entries[0].id == "acme.tool"


@pytest.mark.anyio
async def test_the_ttl_expiring_triggers_exactly_one_new_fetch(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = _cached_client(http, tmp_path, public_key_b64, clock, ttl_seconds=3600)
        await client.fetch()
        clock.advance(3601)
        await client.fetch()
        await client.fetch()

    assert calls["count"] == 2


@pytest.mark.anyio
async def test_a_dead_index_url_is_not_retried_within_the_failure_ttl(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], caplog: pytest.LogCaptureFixture
) -> None:
    """The negative cache: the failure that made #321 hurt — an index host
    that never answers — costs one attempt per failure TTL, not one per
    marketplace request, and the fallback is still served every time."""
    _, public_key_b64 = keypair

    def dead(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    handler, calls = _counting_handler(dead)
    clock = _Clock()

    with caplog.at_level(logging.WARNING, logger="palaia_hub.market.curated"):
        async with _client_for(httpx.MockTransport(handler)) as http:
            client = _cached_client(http, tmp_path, public_key_b64, clock, failure_ttl_seconds=300)
            first = await client.fetch()
            clock.advance(299)
            second = await client.fetch()
            third = await client.fetch()

    assert calls["count"] == 1
    for result in (first, second, third):
        assert result.stale is True
        assert "network error" in result.warning
    # One WARNING for the real failure; the cached repeats do not spam the log.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


@pytest.mark.anyio
async def test_the_failure_ttl_is_shorter_and_expires_into_a_retry(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    state = {"up": False}

    def flaky(_: httpx.Request) -> httpx.Response:
        if not state["up"]:
            raise httpx.ConnectError("still down")
        return httpx.Response(200, content=dump(document))

    handler, calls = _counting_handler(flaky)
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = _cached_client(
            http, tmp_path, public_key_b64, clock, ttl_seconds=3600, failure_ttl_seconds=300
        )
        assert (await client.fetch()).stale is True
        state["up"] = True
        clock.advance(301)
        recovered = await client.fetch()

    assert calls["count"] == 2
    assert recovered.stale is False
    assert recovered.entries[0].id == "acme.tool"


@pytest.mark.anyio
async def test_a_refused_document_is_negatively_cached_too(
    tmp_path: Path, sign_document: Callable[[dict], dict]
) -> None:
    """A document that downloads fine but fails verification is the case
    #321 describes for every hub today (the pinned key is the discarded
    starter key) — it must not be re-downloaded per request either."""
    wrong_key = Ed25519PrivateKey.generate()
    wrong_public_b64 = base64.b64encode(wrong_key.public_key().public_bytes_raw()).decode()
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = _cached_client(http, tmp_path, wrong_public_b64, clock)
        first = await client.fetch()
        second = await client.fetch()

    assert calls["count"] == 1
    assert "signature" in first.warning.lower()
    assert second.warning == first.warning


@pytest.mark.anyio
async def test_force_bypasses_the_cache_but_records_the_outcome(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    """The explicit refresh (``MarketService.refresh_curated_index``) always
    asks the URL — and what it learns is what the next plain fetch serves."""
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        client = _cached_client(http, tmp_path, public_key_b64, clock)
        await client.fetch()
        await client.fetch(force=True)
        await client.fetch()

    assert calls["count"] == 2


@pytest.mark.anyio
async def test_a_changed_key_or_url_does_not_reuse_the_old_outcome(
    tmp_path: Path, keypair: tuple[Ed25519PrivateKey, str], sign_document: Callable[[dict], dict]
) -> None:
    """The cache is keyed by URL *and* public key: fixing ``config.yaml``
    after a failure must take effect at once, not after the failure TTL."""
    _, public_key_b64 = keypair
    document = sign_document(make_document())
    handler, calls = _counting_handler(lambda _: httpx.Response(200, content=dump(document)))
    wrong_key = Ed25519PrivateKey.generate()
    wrong_public_b64 = base64.b64encode(wrong_key.public_key().public_bytes_raw()).decode()
    clock = _Clock()

    async with _client_for(httpx.MockTransport(handler)) as http:
        refused = await _cached_client(http, tmp_path, wrong_public_b64, clock).fetch()
        accepted = await _cached_client(http, tmp_path, public_key_b64, clock).fetch()

    assert calls["count"] == 2
    assert refused.stale is True
    assert accepted.stale is False
