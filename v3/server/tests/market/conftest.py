from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from palaia_hub.market.curated import canonical_bytes

#: The same fixture MCP server ``tests/upstream`` uses — referenced by
#: path rather than by importing that package's own ``conftest.py``
#: fixture (this repo's test layout treats each ``tests/<area>/`` as its
#: own top-level package with no shared parent to import across; see this
#: file's ``http_upstream`` fixture below).
_UPSTREAM_HTTP_SERVER = (
    Path(__file__).resolve().parent.parent / "upstream" / "fixture_http_server.py"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class HttpUpstream:
    """A running fixture MCP server (SPEC-302's, reused here) in its own
    process — SPEC-304's install flow connects to it exactly like a real
    ``remote`` marketplace entry's declared address."""

    url: str
    process: subprocess.Popen[bytes]

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            self.process.kill()
            self.process.wait(timeout=10)


@pytest.fixture
def http_upstream() -> Iterator[HttpUpstream]:
    """An unauthenticated fixture MCP server, in its own process."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, str(_UPSTREAM_HTTP_SERVER), "--port", str(port)]
    )
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 30
    try:
        while time.time() < deadline:
            if process.poll() is not None:  # pragma: no cover - fixture start failure
                raise RuntimeError("the fixture upstream exited before becoming reachable")
            try:
                httpx.post(url, timeout=1.0)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:  # pragma: no cover - fixture start failure
            process.terminate()
            raise RuntimeError("the fixture upstream never became reachable")
        yield HttpUpstream(url=url, process=process)
    finally:
        HttpUpstream(url=url, process=process).stop()


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
