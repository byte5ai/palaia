"""Real Claude Code CLI round-trip against the fake-backed gateway.

SPEC-105 acceptance criterion: "Claude Code connects via `claude mcp add
--transport http` and round-trips write->search->read on a test vault."
Skipped (not failed) when the ``claude`` binary is not on PATH, so CI
environments without it stay green; this sandbox has it, so this test
actually runs and is part of the SPEC's verification evidence.

Also captures gateway-side request logs during the connection, per the
SPEC's binding instructions, to document the known pre-handshake `400`
FINDINGS Q5 observed with FastMCP 3.4.7 against a real Claude Code client.
See ``_e2e_server.py``'s module docstring for what that request actually
is (a pre-``initialize`` ``server/discover`` protocol-version probe, not
the ``Accept``-header issue FINDINGS Q5 guessed at).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_CLAUDE = shutil.which("claude")
pytestmark = pytest.mark.skipif(_CLAUDE is None, reason="claude CLI not on PATH")

_SERVER_SCRIPT = Path(__file__).parent / "_e2e_server.py"
_STARTUP_TIMEOUT = 15.0
_CLAUDE_TIMEOUT = 60.0


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
    raise RuntimeError(f"e2e server did not become healthy within {timeout}s: {last_error}")


def _run_claude(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert _CLAUDE is not None
    return subprocess.run(
        [_CLAUDE, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_CLAUDE_TIMEOUT,
    )


def _claude_call_tool_text(server_name: str, tool: str, prompt: str, cwd: Path) -> str:
    """Run one `claude -p` turn restricted to a single tool, return its raw reply text."""
    full_tool = f"mcp__{server_name}__{tool}"
    result = _run_claude(
        [
            "-p",
            prompt,
            "--allowedTools",
            full_tool,
            "--output-format",
            "json",
        ],
        cwd=cwd,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("is_error") is False, payload
    reply: str = payload["result"]
    return reply


def test_claude_code_connects_and_round_trips_write_search_read(
    tmp_path: Path,
) -> None:
    port = _free_port()
    log_path = tmp_path / "server.log"
    with log_path.open("w") as log_file:
        server_proc = subprocess.Popen(
            [sys.executable, str(_SERVER_SCRIPT), "--port", str(port)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_for_health(port)

            server_name = "palaia-spec105-e2e"
            work_dir = tmp_path / "claude-project"
            work_dir.mkdir()
            mcp_url = f"http://127.0.0.1:{port}/mcp/default/"

            add_result = _run_claude(
                ["mcp", "add", "--transport", "http", server_name, mcp_url, "--scope", "local"],
                cwd=work_dir,
            )
            assert add_result.returncode == 0, add_result.stderr

            try:
                get_result = _run_claude(["mcp", "get", server_name], cwd=work_dir)
                assert "Connected" in get_result.stdout, get_result.stdout

                write_reply = _claude_call_tool_text(
                    server_name,
                    "work_memory_write",
                    "Call the mcp__palaia-spec105-e2e__work_memory_write tool with "
                    "title='E2E Round Trip' and body='hello from the SPEC-105 e2e test' "
                    "and then reply with ONLY the exact raw text the tool returned, "
                    "nothing else.",
                    work_dir,
                )
                assert "E2E Round Trip" in write_reply

                search_reply = _claude_call_tool_text(
                    server_name,
                    "work_memory_search",
                    "Call the mcp__palaia-spec105-e2e__work_memory_search tool with "
                    "query='round trip' and then reply with ONLY the exact raw text "
                    "the tool returned, nothing else.",
                    work_dir,
                )
                assert "E2E Round Trip" in search_reply

                read_reply = _claude_call_tool_text(
                    server_name,
                    "work_memory_read",
                    "Call the mcp__palaia-spec105-e2e__work_memory_read tool with "
                    "permalink='e2e-round-trip' and then reply with ONLY the exact "
                    "raw text the tool returned, nothing else.",
                    work_dir,
                )
                assert "hello from the SPEC-105 e2e test" in read_reply
            finally:
                _run_claude(["mcp", "remove", server_name, "-s", "local"], cwd=work_dir)
        finally:
            server_proc.terminate()
            try:
                server_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                server_proc.kill()
                server_proc.wait(timeout=5)

    # Evidence for FINDINGS Q5's pre-handshake 400: assert it happened (so
    # this test documents the behavior, not just tolerates it) and that our
    # diagnostic middleware identified the request.
    log_text = log_path.read_text()
    assert ' 400 Bad Request' in log_text or '" 400 ' in log_text, (
        "expected the known FastMCP 3.4.7 pre-handshake 400 in the gateway "
        f"log; log was:\n{log_text}"
    )
    assert "DIAGNOSTIC 400" in log_text, (
        f"diagnostic middleware did not capture the 400's request details; log was:\n{log_text}"
    )
