"""SPEC-303 acceptance: a tampered curated index (bad signature, wrong
key, downgraded generated_at) is refused and the last good copy served,
with a WARNING naming the reason."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path

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
