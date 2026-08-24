from __future__ import annotations

import base64
import json
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.market.curated import canonical_bytes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def keypair() -> tuple[Ed25519PrivateKey, str]:
    """A fresh Ed25519 keypair; ``(private_key, public_key_b64)``."""
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes_raw()
    return private_key, base64.b64encode(public_raw).decode()


@pytest.fixture
def sign_document(keypair: tuple[Ed25519PrivateKey, str]) -> Callable[[dict], dict]:
    private_key, _ = keypair

    def _sign(document: dict) -> dict:
        document = dict(document)
        document.pop("signature", None)
        signature = private_key.sign(canonical_bytes(document))
        document["signature"] = base64.b64encode(signature).decode()
        return document

    return _sign


def make_entry(entry_id: str = "acme.tool") -> dict:
    return {
        "id": entry_id,
        "name": "Acme Tool",
        "one_liner": "Does the acme thing.",
        "kind": "container",
        "source": {"type": "image", "value": "ghcr.io/acme/tool:1.0.0"},
        "permissions": ["network"],
        "maintainer": "acme",
        "verified": True,
    }


def make_document(
    generated_at: str = "2026-08-24T00:00:00Z", entries: list[dict] | None = None
) -> dict:
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "entries": entries if entries is not None else [make_entry()],
    }


def dump(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")
