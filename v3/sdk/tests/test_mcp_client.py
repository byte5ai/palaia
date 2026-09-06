"""Issue #354: ``palaia-addon test`` must report a silent add-on, not hang.

``StdioMcpClient`` read the child's stderr on the timeout path with a
blocking ``read(4096)`` — an add-on that logged one short line and then
never answered ``initialize`` blocked the client forever, in exactly the
situation the timeout exists to describe. And a child that had to be killed
was never waited for, leaving a zombie behind.
"""

from __future__ import annotations

import sys
import time

import pytest

from palaia_addon_sdk.mcp_client import McpClientError, StdioMcpClient

SILENT_ADDON = (
    "import sys, time\nprint('booting the add-on', file=sys.stderr, flush=True)\ntime.sleep(60)\n"
)

STUBBORN_ADDON = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "print('ignoring SIGTERM', file=sys.stderr, flush=True)\n"
    "time.sleep(60)\n"
)


def test_a_silent_add_on_is_reported_with_its_stderr_within_the_timeout() -> None:
    started = time.monotonic()
    with StdioMcpClient([sys.executable, "-c", SILENT_ADDON], timeout=1.0) as client:
        with pytest.raises(McpClientError, match="did not answer within") as info:
            client.initialize_and_list_tools()
        assert "booting the add-on" in str(info.value)

    assert time.monotonic() - started < 15, "the timeout path must not block on stderr"
    proc = client._proc
    assert proc is not None and proc.returncode is not None, "the child was reaped"


def test_a_child_that_ignores_termination_is_killed_and_reaped() -> None:
    with StdioMcpClient([sys.executable, "-c", STUBBORN_ADDON], timeout=1.0) as client:
        with pytest.raises(McpClientError):
            client.initialize_and_list_tools()

    proc = client._proc
    assert proc is not None
    assert proc.returncode is not None, "killed *and* waited for — no zombie"
