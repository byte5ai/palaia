"""A session a client ends leaves no error in the hub's log (issue #627).

A real hub process and a real streamable-HTTP client: the client opens its
event stream (``GET``), lists the tools and ends the session (``DELETE``).
On that path ``mcp`` 1.x logged "Error in standalone SSE writer" with a
traceback for every session (see :class:`palaia_hub.logging.SessionEndFilter`).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio

_SESSIONS = 2


def _log_once_sessions_ended(log_path: Path, sessions: int, *, timeout: float = 10.0) -> str:
    """The hub's log once it has torn down ``sessions`` sessions.

    The library logged its error right after "Terminating session", from the
    event stream's writer task; the short wait after the last one gives that
    task the time to run before the log is read.
    """
    deadline = time.monotonic() + timeout
    while log_path.read_text(encoding="utf-8").count("Terminating session") < sessions:
        if time.monotonic() > deadline:
            break
        time.sleep(0.1)
    time.sleep(0.5)
    return log_path.read_text(encoding="utf-8")


async def test_an_ended_session_logs_no_error(tmp_path: Path, hub_factory: HubFactory) -> None:
    hub = hub_factory(vault_dir=tmp_path / "vault")

    for _ in range(_SESSIONS):
        async with SimulatedClient(hub.profile_url(), client_name="session-end") as client:
            assert await client.list_tools()

    log = _log_once_sessions_ended(hub.log_path, _SESSIONS)

    # The path this test is about ran: each client held an event stream
    # open and ended its session with a DELETE.
    assert log.count('"GET /mcp/default/ HTTP/1.1" 200') == _SESSIONS, log
    assert log.count('"DELETE /mcp/default/ HTTP/1.1" 200') == _SESSIONS, log
    assert log.count("Terminating session") == _SESSIONS, log

    assert "Error in standalone SSE writer" not in log, log
    assert "Traceback" not in log, log
