"""Tests for the SPEC-109 live-state layer: /api/events (SSE).

A real streaming response never completes until the client disconnects,
and httpx's in-process ASGI transport (which backs FastAPI's
``TestClient``) buffers an entire ASGI app call before handing back
*any* of the response — it cannot observe an indefinite stream at all.
So, like ``test_cli_serve.py``, these tests spawn a real
``palaia-hub serve`` subprocess and read the response incrementally off
a real socket.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

_STARTUP_TIMEOUT = 10.0
_SHUTDOWN_TIMEOUT = 10.0
_LINE_TIMEOUT = 10.0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, timeout: float = _STARTUP_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            if resp.status == 200:
                resp.read()
                conn.close()
                return
            conn.close()
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise RuntimeError(f"hub did not become healthy within {timeout}s: {last_error}")


def _spawn_hub(tmp_path: Path, port: int, *, extra_env: dict[str, str]) -> subprocess.Popen[str]:
    env = dict(os.environ)
    env["PALAIA_HOME"] = str(tmp_path)
    env["PALAIA_HOST"] = "127.0.0.1"
    env["PALAIA_PORT"] = str(port)
    env.update(extra_env)
    return subprocess.Popen(
        [sys.executable, "-m", "palaia_hub", "serve"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_hub(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _open_event_stream(port: int) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=_LINE_TIMEOUT)
    conn.request("GET", "/api/events")
    resp = conn.getresponse()
    return conn, resp


def _read_one_sse_event(resp: http.client.HTTPResponse) -> dict[str, object]:
    """Read lines up to (and past) the next blank line and return its payload."""
    data: dict[str, object] | None = None
    while True:
        raw = resp.readline()
        if not raw:
            raise AssertionError("event stream closed before a full event arrived")
        line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
        if line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
        elif line == "":
            if data is not None:
                return data
            # a blank keep-alive line with no preceding data: keep reading


def test_events_stream_sends_an_immediate_health_snapshot(tmp_path: Path) -> None:
    port = _free_port()
    proc = _spawn_hub(tmp_path, port, extra_env={"PALAIA_HEALTH_EVENT_INTERVAL_SECONDS": "60"})
    try:
        _wait_for_health(port)
        conn, resp = _open_event_stream(port)
        try:
            assert resp.status == 200
            assert resp.getheader("Content-Type", "").startswith("text/event-stream")
            event = _read_one_sse_event(resp)
        finally:
            conn.close()
    finally:
        _stop_hub(proc)

    assert event["type"] == "health"
    data = event["data"]
    assert isinstance(data, dict)
    assert data["status"] == "ok"
    assert "ts" in event


def test_events_stream_emits_periodic_health_ticks(tmp_path: Path) -> None:
    port = _free_port()
    proc = _spawn_hub(tmp_path, port, extra_env={"PALAIA_HEALTH_EVENT_INTERVAL_SECONDS": "0.05"})
    try:
        _wait_for_health(port)
        conn, resp = _open_event_stream(port)
        try:
            first = _read_one_sse_event(resp)
            second = _read_one_sse_event(resp)
        finally:
            conn.close()
    finally:
        _stop_hub(proc)

    assert first["type"] == second["type"] == "health"


def test_vault_change_on_disk_publishes_a_vault_changed_event(tmp_path: Path) -> None:
    """The acceptance-criterion scenario: a vault file touched on disk
    produces an event on the stream without any page reload — the
    client-side "reload" is exactly the SSE connection staying open.
    """
    watch_dir = tmp_path / "vault"
    watch_dir.mkdir()
    port = _free_port()
    proc = _spawn_hub(
        tmp_path / "home",
        port,
        extra_env={
            "PALAIA_HEALTH_EVENT_INTERVAL_SECONDS": "60",
            "PALAIA_WATCH_DIR": str(watch_dir),
        },
    )
    try:
        _wait_for_health(port)
        conn, resp = _open_event_stream(port)
        try:
            _read_one_sse_event(resp)  # the immediate health snapshot

            (watch_dir / "note.md").write_text("# a note\n", encoding="utf-8")

            deadline = time.monotonic() + 15.0
            vault_event: dict[str, object] | None = None
            while time.monotonic() < deadline:
                event = _read_one_sse_event(resp)
                if event["type"] == "vault_changed":
                    vault_event = event
                    break
        finally:
            conn.close()
    finally:
        _stop_hub(proc)

    assert vault_event is not None, "expected a vault_changed event within the debounce budget"
    data = vault_event["data"]
    assert isinstance(data, dict)
    assert data["count"] >= 1
    assert any("note.md" in path for path in data["paths"])


def test_events_route_is_not_shadowed_by_the_dashboard_mount(tmp_path: Path) -> None:
    """/api/events must keep working even once a dashboard build is mounted.

    The SPA static-file fallback (static.mount_dashboard) answers *any*
    unmatched path with index.html — this proves it never gets a chance
    to see /api/events, by exercising both together end-to-end.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<!doctype html><title>palaia</title>", encoding="utf-8")

    port = _free_port()
    proc = _spawn_hub(
        tmp_path / "home",
        port,
        extra_env={
            "PALAIA_HEALTH_EVENT_INTERVAL_SECONDS": "60",
            "PALAIA_WEB_DIST": str(dist_dir),
        },
    )
    try:
        _wait_for_health(port)

        conn, resp = _open_event_stream(port)
        try:
            assert resp.status == 200
            assert resp.getheader("Content-Type", "").startswith("text/event-stream")
        finally:
            conn.close()

        html_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=_LINE_TIMEOUT)
        html_conn.request("GET", "/some/deep/link")
        html_resp = html_conn.getresponse()
        body = html_resp.read().decode("utf-8")
        html_conn.close()
        assert html_resp.status == 200
        assert "palaia" in body
    finally:
        _stop_hub(proc)
