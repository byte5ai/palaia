"""SPEC-306 acceptance criteria for `palaia-proxy.mjs`, the real script.

Everything here spawns the *actual* file at
``v3/tools/build-mcpb/proxy/palaia-proxy.mjs`` as a Node subprocess and
drives it with `fastmcp.Client` over a real stdio transport — the exact
proof shape SPEC-002's gateway spike used, applied to the proxy instead of
the gateway. On the other side of the proxy is a real hub subprocess
(``support/hub_server_token.py``): a real ``VaultEngine``, a real SPEC-108
``TokenStore``-backed ``TokenVerifier``, a real ``uvicorn`` socket — the
proxy speaks real streamable HTTP to it over a real loopback TCP
connection, never an ASGI shortcut.

Covers:

- "stdio e2e through the real proxy against a real hub: tools listed and
  a memory tool called successfully" (deliverable #5).
- "proxy survives hub restart (reconnect test)".
- "reports a clear error on wrong credentials (no stack trace vomit)".

Skipped, not failed, when `node` is not on PATH — the same honesty rule
the `claude`-CLI-gated tests in this directory already follow.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO

import pytest

from palaia_hub.auth.store import TokenStore

_NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(_NODE is None, reason="node is not on PATH")

_PROXY_SCRIPT = (
    Path(__file__).resolve().parents[3] / "tools" / "build-mcpb" / "proxy" / "palaia-proxy.mjs"
)
_HUB_SCRIPT = Path(__file__).parent / "support" / "hub_server_token.py"
_STARTUP_TIMEOUT = 20.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=0.5
            ) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"hub did not become healthy within {timeout}s: {last_error}")


def _start_hub(
    *, port: int, vault_dir: Path, token_store_dir: Path, log_path: Path
) -> tuple[subprocess.Popen[bytes], IO[str]]:
    args = [
        sys.executable,
        str(_HUB_SCRIPT),
        "--port",
        str(port),
        "--vault-dir",
        str(vault_dir),
        "--token-store-dir",
        str(token_store_dir),
    ]
    log_file = log_path.open("w")
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        args, stdout=log_file, stderr=subprocess.STDOUT
    )
    return process, log_file


def _stop_hub(process: subprocess.Popen[bytes], log_file: IO[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.wait(timeout=5)
    log_file.close()


def _proxy_env(*, hub_url: str, token: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PALAIA_HUB_URL"] = hub_url
    env["PALAIA_TOKEN"] = token
    env["PALAIA_LOG_LEVEL"] = "debug"
    return env


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_tools_listed_and_a_memory_tool_called_through_the_real_proxy(
    tmp_path: Path,
) -> None:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    port = _free_port()
    vault_dir = tmp_path / "vault"
    token_store_dir = tmp_path / "tokens"
    token_store_dir.mkdir()
    token = TokenStore(home=token_store_dir).create(
        "e2e proxy", "default", ["vault:work:read", "vault:work:write"]
    ).token

    process, log_file = _start_hub(
        port=port,
        vault_dir=vault_dir,
        token_store_dir=token_store_dir,
        log_path=tmp_path / "hub.log",
    )
    try:
        _wait_for_health(port)
        hub_url = f"http://127.0.0.1:{port}/mcp/default/"
        transport = StdioTransport(
            command="node",
            args=[str(_PROXY_SCRIPT)],
            env=_proxy_env(hub_url=hub_url, token=token),
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            tool_names = {t.name for t in tools}
            assert "work_memory_write" in tool_names
            assert "work_memory_search" in tool_names

            write_result = await client.call_tool(
                "work_memory_write",
                {"title": "Proxy E2E", "body": "written through palaia-proxy.mjs over real stdio"},
            )
            assert write_result.is_error is not True

            search_result = await client.call_tool(
                "work_memory_search", {"query": "palaia-proxy"}
            )
            assert search_result.is_error is not True
            assert "Proxy E2E" in str(search_result.content)
    finally:
        _stop_hub(process, log_file)


@pytest.mark.anyio
async def test_proxy_survives_a_hub_restart(tmp_path: Path) -> None:
    """Reconnect test: the hub is killed mid-session and restarted on the
    same port; a call made after the restart still succeeds — proving the
    proxy's own backoff/retry (not a fresh proxy process) recovered."""
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    port = _free_port()
    vault_dir = tmp_path / "vault"
    token_store_dir = tmp_path / "tokens"
    token_store_dir.mkdir()
    token = TokenStore(home=token_store_dir).create(
        "e2e proxy restart", "default", ["vault:work:read", "vault:work:write"]
    ).token

    process, log_file = _start_hub(
        port=port,
        vault_dir=vault_dir,
        token_store_dir=token_store_dir,
        log_path=tmp_path / "hub1.log",
    )
    hub_url = f"http://127.0.0.1:{port}/mcp/default/"
    transport = StdioTransport(
        command="node", args=[str(_PROXY_SCRIPT)], env=_proxy_env(hub_url=hub_url, token=token)
    )
    try:
        _wait_for_health(port)
        async with Client(transport) as client:
            first = await client.call_tool(
                "work_memory_write", {"title": "Before restart", "body": "before"}
            )
            assert first.is_error is not True

            _stop_hub(process, log_file)

            process, log_file = _start_hub(
                port=port,
                vault_dir=vault_dir,
                token_store_dir=token_store_dir,
                log_path=tmp_path / "hub2.log",
            )
            _wait_for_health(port)

            second = await client.call_tool(
                "work_memory_write", {"title": "After restart", "body": "after"}
            )
            assert second.is_error is not True
    finally:
        _stop_hub(process, log_file)


@pytest.mark.anyio
async def test_wrong_credentials_report_a_clear_error_not_a_stack_trace(tmp_path: Path) -> None:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    from mcp import McpError

    port = _free_port()
    vault_dir = tmp_path / "vault"
    token_store_dir = tmp_path / "tokens"
    token_store_dir.mkdir()
    # A token is minted, then revoked — a live "wrong credentials" case,
    # not just a malformed string.
    store = TokenStore(home=token_store_dir)
    created = store.create("e2e wrong creds", "default", ["vault:work:read"])
    store.revoke(created.info.id)

    process, log_file = _start_hub(
        port=port,
        vault_dir=vault_dir,
        token_store_dir=token_store_dir,
        log_path=tmp_path / "hub.log",
    )
    try:
        _wait_for_health(port)
        hub_url = f"http://127.0.0.1:{port}/mcp/default/"
        transport = StdioTransport(
            command="node",
            args=[str(_PROXY_SCRIPT)],
            env=_proxy_env(hub_url=hub_url, token=created.token),
        )
        with pytest.raises(McpError) as exc_info:
            async with Client(transport) as client:
                await client.list_tools()

        message = str(exc_info.value)
        assert "Traceback" not in message
        assert " at " not in message  # no JS stack frame syntax leaked through
    finally:
        _stop_hub(process, log_file)
