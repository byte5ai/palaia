"""Integration tests that spawn a real ``palaia-hub serve`` subprocess.

These exercise behavior that only exists once uvicorn's real event loop and
signal handling are involved: starting from zero config, and completing an
in-flight request before exiting on SIGTERM.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_STARTUP_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 10.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"hub did not become healthy within {timeout}s: {last_error}")


def _spawn_hub(
    tmp_path: Path, port: int, *, slow_seconds: float | None = None
) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PALAIA_HOME"] = str(tmp_path)
    env["PALAIA_HOST"] = "127.0.0.1"
    env["PALAIA_PORT"] = str(port)
    if slow_seconds is not None:
        env["PALAIA_TEST_SLOW_ENDPOINT_SECONDS"] = str(slow_seconds)
    return subprocess.Popen(
        [sys.executable, "-m", "palaia_hub", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_serve_starts_with_zero_config_and_health_is_green(tmp_path: Path) -> None:
    port = _free_port()
    proc = _spawn_hub(tmp_path, port)
    try:
        _wait_for_health(port)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
            assert resp.status == 200
        # Zero-config first run must have created the default file.
        assert (tmp_path / "config.yaml").exists()
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=_SHUTDOWN_TIMEOUT)


def test_sigterm_lets_inflight_request_finish_then_exits(tmp_path: Path) -> None:
    port = _free_port()
    proc = _spawn_hub(tmp_path, port, slow_seconds=1.5)
    try:
        _wait_for_health(port)

        result: dict[str, object] = {}

        def _call_slow() -> None:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/_test/slow", timeout=_SHUTDOWN_TIMEOUT
                ) as resp:
                    result["status"] = resp.status
            except Exception as exc:  # pragma: no cover - asserted below
                result["error"] = repr(exc)

        thread = threading.Thread(target=_call_slow)
        thread.start()
        time.sleep(0.3)  # let the slow request actually start before SIGTERM

        proc.send_signal(signal.SIGTERM)
        thread.join(timeout=_SHUTDOWN_TIMEOUT)

        assert result.get("status") == 200, f"slow request did not complete cleanly: {result}"

        # uvicorn drains gracefully, then re-raises the captured signal so the
        # process reports as signal-terminated (standard Unix daemon
        # semantics) — the point being tested is that this happens *after*
        # the in-flight request above already got its 200, not that the
        # process exits with code 0.
        returncode = proc.wait(timeout=_SHUTDOWN_TIMEOUT)
        assert returncode == -signal.SIGTERM, proc.stdout.read() if proc.stdout else returncode
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
