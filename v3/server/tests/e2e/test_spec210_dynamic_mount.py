"""SPEC-210 deliverable #1: dynamic gateway mounting.

Boots a hub with zero vaults (see ``support/hub_server_dynamic.py``),
creates one through the wizard's own ``POST /api/vaults`` (real HTTP, the
same call the dashboard makes), and then calls an MCP tool against it over
real streamable HTTP — all against the one process the test started,
proving no restart happened in between.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from simulator import SimulatedClient

_SCRIPT = Path(__file__).parent / "support" / "hub_server_dynamic.py"
_STARTUP_TIMEOUT = 15.0

pytestmark = pytest.mark.anyio


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


def _post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        return dict(json.loads(resp.read()))


@pytest.fixture
def dynamic_hub(tmp_path: Path):  # noqa: ANN201 - yields a bare port int
    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    log_path = tmp_path / "hub.log"
    args = [sys.executable, str(_SCRIPT), "--port", str(port), "--home", str(home)]
    with log_path.open("w") as log_file:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            args, stdout=log_file, stderr=subprocess.STDOUT
        )
    try:
        _wait_for_health(port)
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


async def test_vault_created_via_api_is_reachable_by_mcp_without_restart(
    dynamic_hub: int,
) -> None:
    port = dynamic_hub

    # Nothing mounted yet: the profile path 404s before any vault exists.
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/mcp/default/", timeout=5)
    assert exc_info.value.code == 404

    created = _post_json(
        f"http://127.0.0.1:{port}/api/vaults",
        {"key": "runtime", "purpose": "Created at runtime by this test.", "template": True},
    )
    assert created["key"] == "runtime"

    # Same process, same port, no restart in between — a real MCP client
    # can now reach the vault's tool family through the default profile.
    async with SimulatedClient(
        f"http://127.0.0.1:{port}/mcp/default/", client_name="spec-210-e2e"
    ) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert "runtime_memory_search" in names
        assert "runtime_memory_write" in names

        write_result = await client.call_tool_ok(
            "runtime_memory_write",
            {"title": "Dynamic Mount Note", "body": "written without a hub restart"},
        )
        assert "Dynamic Mount Note" in write_result.text

        search_result = await client.call_tool_ok(
            "runtime_memory_search", {"query": "Dynamic Mount Note"}
        )
        assert "Dynamic Mount Note" in search_result.text


async def test_two_vaults_created_at_runtime_are_both_reachable(dynamic_hub: int) -> None:
    port = dynamic_hub
    for key in ("alpha", "beta"):
        created = _post_json(f"http://127.0.0.1:{port}/api/vaults", {"key": key})
        assert created["key"] == key

    async with SimulatedClient(
        f"http://127.0.0.1:{port}/mcp/default/", client_name="spec-210-e2e-two"
    ) as client:
        names = {t.name for t in await client.list_tools()}
        assert "alpha_memory_search" in names
        assert "beta_memory_search" in names
