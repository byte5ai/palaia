"""Fixtures for SPEC-302: a real HTTP upstream in its own process, a real
stdio upstream command, and a hub home with a secret store.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from palaia_hub.upstream.secrets import SecretStore

HERE = Path(__file__).parent
HTTP_SERVER = HERE / "fixture_http_server.py"
STDIO_SERVER = HERE / "fixture_stdio_server.py"

#: The token ``http_upstream`` demands when started with one. Test-only.
FIXTURE_BEARER_TOKEN = "fixture-upstream-token"  # noqa: S105 - test fixture, not a credential


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class HttpUpstream:
    """A running fixture MCP server in its own process."""

    url: str
    process: subprocess.Popen[bytes]

    def stop(self) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - stubborn child
            self.process.kill()
            self.process.wait(timeout=10)


def _start_http_upstream(*, require_token: str | None) -> HttpUpstream:
    port = _free_port()
    command = [sys.executable, str(HTTP_SERVER), "--port", str(port)]
    if require_token:
        command += ["--require-token", require_token]
    process = subprocess.Popen(command)
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:  # pragma: no cover - fixture start failure
            raise RuntimeError("the fixture upstream exited before becoming reachable")
        try:
            # Any answer at all (including 401/406) proves the socket is up;
            # the MCP handshake itself is what the tests exercise.
            httpx.post(url, timeout=1.0)
            return HttpUpstream(url=url, process=process)
        except httpx.HTTPError:
            time.sleep(0.1)
    process.terminate()  # pragma: no cover - fixture start failure
    raise RuntimeError("the fixture upstream never became reachable")  # pragma: no cover


@pytest.fixture
def http_upstream() -> Iterator[HttpUpstream]:
    """An unauthenticated fixture MCP server, in its own process."""
    upstream = _start_http_upstream(require_token=None)
    try:
        yield upstream
    finally:
        upstream.stop()


@pytest.fixture
def http_upstream_with_token() -> Iterator[HttpUpstream]:
    """A fixture MCP server that requires :data:`FIXTURE_BEARER_TOKEN`."""
    upstream = _start_http_upstream(require_token=FIXTURE_BEARER_TOKEN)
    try:
        yield upstream
    finally:
        upstream.stop()


@pytest.fixture
def secret_store(tmp_path: Path) -> Iterator[SecretStore]:
    store = SecretStore(tmp_path / "home")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def stdio_command() -> list[str]:
    """The command line for the stdio fixture upstream."""
    return [sys.executable, str(STDIO_SERVER)]
