"""S7 "the first-run funnel, scripted end to end" (SPEC-504).

The acceptance criterion this test is: "a scripted first-run walk (API-
level: fresh home -> wizard endpoints -> vault -> token -> first memory
write) completes without any step that requires editing a file or a shell
beyond the install one-liner." Every step below is a real HTTP call or a
real MCP tool call against one hub process booted from a genuinely empty
home directory — the same process, no restart, exactly what a first-timer
following the onboarding page would trigger by clicking through the
dashboard wizard:

1. Boot a hub against an empty `PALAIA_HOME` (SPEC-210's
   `hub_server_dynamic.py`, `--auth-enabled` this time — a token that is
   never checked would not prove anything about "connect a client").
2. `POST /api/vaults` — the wizard's "first vault" step.
3. `POST /api/auth/tokens` — the wizard's "connect a client" step, minting
   a real per-client token the way `ConnectPanel` does.
4. A real MCP client, authenticated with that token over real streamable
   HTTP, writes the first note — the funnel's headline moment.
5. `GET /api/funnel/status` — proves the hub recorded every step's
   timestamp itself (SPEC-504 deliverable #3) and derived a
   time-to-first-memory, with no step requiring a shell command or a file
   edit beyond the one `docker run`/dynamic_hub launch already covered.
"""

from __future__ import annotations

import json
import re
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


def _get_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return dict(json.loads(resp.read()))


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
def fresh_hub(tmp_path: Path):  # noqa: ANN201 - yields a bare port int
    """A hub subprocess against a truly empty home directory, auth enabled."""
    port = _free_port()
    home = tmp_path / "home"
    home.mkdir()
    assert not (home / "vaults.yaml").exists(), "this must start as a genuinely fresh install"
    log_path = tmp_path / "hub.log"
    args = [
        sys.executable,
        str(_SCRIPT),
        "--port",
        str(port),
        "--home",
        str(home),
        "--auth-enabled",
    ]
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


async def test_fresh_install_wizard_walk_records_time_to_first_memory(
    fresh_hub: int,
) -> None:
    port = fresh_hub
    base = f"http://127.0.0.1:{port}"

    # Step 0: the wizard's landing page polls these before offering
    # "create your first vault" — both already real, merged surfaces.
    info = _get_json(f"{base}/api/info")
    assert info["mode"] == "locked"

    # hub.started already recorded the funnel's own start line, the
    # moment the process came up — before this test does anything else.
    status = _get_json(f"{base}/api/funnel/status")
    assert status["hub_started_at"] is not None
    assert status["vault_created_at"] is None
    assert status["client_connected_at"] is None
    assert status["first_memory_at"] is None
    assert status["time_to_first_memory_seconds"] is None
    assert status["time_to_first_memory_display"] is None

    # Step 1: the wizard's "first vault" step — real HTTP, no shell, no
    # file edit. `template` stays off, matching `Onboarding.tsx`'s own
    # default (that switch starts unchecked) — the funnel-audit finding on
    # why this matters is in `palaia_hub.funnel`'s module docstring: a
    # template vault's two seed notes are themselves `memory.entry.created`
    # events, so opting into them would make "first memory" fire before
    # the client the wizard is trying to measure ever writes anything.
    created = _post_json(
        f"{base}/api/vaults",
        {"key": "work", "purpose": "The first-run funnel walk's vault."},
    )
    assert created["key"] == "work"

    status = _get_json(f"{base}/api/funnel/status")
    assert status["vault_created_at"] is not None
    assert status["client_connected_at"] is None
    assert status["first_memory_at"] is None

    # Step 2: the wizard's "connect a client" step — issuing a token is a
    # real API call, exactly what ConnectPanel.tsx does under "Issue
    # token".
    issued = _post_json(
        f"{base}/api/auth/tokens",
        {"name": "first-run-funnel-client", "profile": "default"},
    )
    token = issued["token"]
    assert isinstance(token, str) and token.startswith("plt_")

    # Step 3: the actual headline moment — a real MCP client, carrying
    # that token, writes the first note over real streamable HTTP.
    async with SimulatedClient(
        f"{base}/mcp/default/", client_name="spec-504-first-run", token=token
    ) as client:
        write_result = await client.call_tool_ok(
            "work_memory_write",
            {"title": "My First Memory", "body": "the first-run funnel's headline moment"},
        )
        assert "My First Memory" in write_result.text

    # Step 4: the hub recorded every step itself, from real server-side
    # events — nothing here came from a client-supplied timestamp.
    status = _get_json(f"{base}/api/funnel/status")
    assert status["vault_created_at"] is not None
    assert status["client_connected_at"] is not None
    assert status["first_memory_at"] is not None
    assert status["hub_started_at"] <= status["vault_created_at"]
    assert status["vault_created_at"] <= status["client_connected_at"]
    assert status["client_connected_at"] <= status["first_memory_at"]

    seconds = status["time_to_first_memory_seconds"]
    assert isinstance(seconds, (int, float)) and seconds >= 0

    display = status["time_to_first_memory_display"]
    assert isinstance(display, str)
    # "37s", "4m12s", "1h03m" — the tile label format (funnel.format_duration).
    assert re.fullmatch(r"(\d+h\d{2}m|\d+m\d{2}s|\d+s)", display), display


async def test_a_read_only_scoped_client_gets_a_fix_naming_error(fresh_hub: int) -> None:
    """SPEC-504 deliverable #2's error-message audit, the real end-to-end
    shape: a client whose token has only ``vault:work:read`` (an explicit,
    narrower scope than the default a wizard-issued token now gets — see
    ``server/tests/auth/test_routes_default_scopes.py``) tries the write
    tool and gets an error that names the fix, over a real HTTP MCP call —
    ``server/tests/funnel/test_error_message_audit.py`` covers the same
    message at the unit level, fast; this is the slower proof that the
    real transport delivers it unchanged."""
    port = fresh_hub
    base = f"http://127.0.0.1:{port}"

    _post_json(f"{base}/api/vaults", {"key": "work"})
    issued = _post_json(
        f"{base}/api/auth/tokens",
        {"name": "read-only-client", "profile": "default", "scopes": ["vault:work:read"]},
    )
    token = issued["token"]

    async with SimulatedClient(
        f"{base}/mcp/default/", client_name="spec-504-scope-audit", token=token
    ) as client:
        result = await client.call_tool(
            "work_memory_write", {"title": "x", "body": "y"}
        )

    assert result.is_error
    assert "Fix:" in result.text
    assert "vault:work:write" in result.text
