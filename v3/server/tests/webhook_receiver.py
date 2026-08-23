"""``LocalReceiver``: SPEC-201's "local receiver" the webhook and
event-bridge acceptance tests POST against.

A real ``http.server.ThreadingHTTPServer`` on a free port, not a mock — a
hub subprocess (``tests/test_events.py``) or an in-process
:class:`~palaia_hub.hooks.delivery.HookDispatcher`
(``tests/hooks/test_delivery.py``) delivers to it over a real socket,
exactly as it would to any operator's receiver. Its
``status_code``/``fail_until`` knobs are what let tests drive retry,
dead-letter, and durability scenarios deterministically.

Deliberately its own module rather than living in ``conftest.py``: several
sibling test directories each have their own ``conftest.py`` with no
``__init__.py`` isolating them, so a plain ``from conftest import ...`` in
a test module collides across directories under pytest's default import
mode — a distinctly-named module sidesteps that entirely.
"""

from __future__ import annotations

import http.server
import socket
import threading
from dataclasses import dataclass, field


@dataclass
class ReceivedRequest:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class LocalReceiver:
    """A real local HTTP server that records what it received."""

    status_code: int = 200
    #: When set, the first ``fail_until`` requests get this status instead
    #: of ``status_code`` — simulates "receiver was down for N attempts,
    #: then recovered", for retry tests.
    fail_until: int = 0
    requests: list[ReceivedRequest] = field(default_factory=list)
    _server: http.server.ThreadingHTTPServer | None = field(default=None, init=False)
    _thread: threading.Thread | None = field(default=None, init=False)

    def start(self) -> None:
        receiver = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib API name
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                receiver.requests.append(
                    ReceivedRequest(
                        method="POST",
                        path=self.path,
                        headers=dict(self.headers.items()),
                        body=body,
                    )
                )
                attempt = len(receiver.requests)
                status = (
                    599
                    if receiver.fail_until and attempt <= receiver.fail_until
                    else receiver.status_code
                )
                self.send_response(status)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass  # silence stderr noise in test output

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}/hook"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


__all__ = ["LocalReceiver", "ReceivedRequest"]
