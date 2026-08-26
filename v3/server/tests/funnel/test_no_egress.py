"""SPEC-504 acceptance criterion: "a test proves no network egress from the
stats path" (MASTERPLAN §10's privacy principle — see
``palaia_hub.funnel``'s own module docstring for the "local-only, by
construction" claim this test backs up).

Patches ``socket.socket.connect``/``connect_ex`` — the two calls every
network client in the standard library and every third-party HTTP library
(``requests``, ``httpx``, ``urllib``) ultimately makes to reach a remote
host — so *nothing* downstream of them can reach the network, no matter
how it tries. The whole funnel path (recording every step, reading the
status back over a real HTTP request against the real FastAPI app) is
exercised underneath that patch; if anything on the path ever tried to
connect out, this test would fail at that call site instead of quietly
passing.

Only ``AF_INET``/``AF_INET6`` connect attempts are blocked, not
``AF_UNIX``: ``fastapi.testclient.TestClient`` itself talks to the ASGI app
in-process over a local Unix ``socketpair`` it opens for its own worker
thread (an implementation detail of ``anyio.from_thread``, nothing to do
with the network) — blocking that too would make this test fail for a
reason that has nothing to do with the claim it exists to check.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.events.bus import EventBus, publish_event
from palaia_hub.funnel import FunnelStore, wire_funnel_tracking

_NETWORK_FAMILIES = {socket.AF_INET, socket.AF_INET6}


class _NetworkAttempted(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _forbid_network_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _blocked_connect(self: socket.socket, address: object) -> object:
        if self.family in _NETWORK_FAMILIES:
            raise _NetworkAttempted(
                f"a funnel code path tried to open a real network connection to "
                f"{address!r} — the funnel store must never make a network call "
                f"of any kind"
            )
        return real_connect(self, address)  # type: ignore[arg-type]

    def _blocked_connect_ex(self: socket.socket, address: object) -> object:
        if self.family in _NETWORK_FAMILIES:
            raise _NetworkAttempted(
                f"a funnel code path tried to open a real network connection to "
                f"{address!r} — the funnel store must never make a network call "
                f"of any kind"
            )
        return real_connect_ex(self, address)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)


def test_recording_every_step_touches_no_socket(tmp_path: Path) -> None:
    bus = EventBus()
    store = FunnelStore(tmp_path)
    wire_funnel_tracking(bus, store)

    publish_event(bus, "hub.started", origin="hub", data={})
    publish_event(bus, "memory.vault.created", origin="dashboard", data={"key": "work"})
    publish_event(bus, "client.connected", origin="auth", data={"token_id": "t1"})
    publish_event(bus, "memory.entry.created", origin="vault", data={"kind": "created"})

    status = store.status()
    assert status.first_memory_at is not None
    assert status.time_to_first_memory_display is not None


def test_reading_funnel_status_over_http_touches_no_socket(tmp_path: Path) -> None:
    app = create_app(HubConfig(), home=tmp_path)
    client = TestClient(app)

    response = client.get("/api/funnel/status")

    assert response.status_code == 200


def test_reopening_the_store_from_disk_touches_no_socket(tmp_path: Path) -> None:
    FunnelStore(tmp_path).record_first_memory(123.0)

    reopened = FunnelStore(tmp_path)
    assert reopened.status().first_memory_at == 123.0


def test_the_block_itself_actually_catches_a_real_attempt() -> None:
    """A positive control: without this, the three tests above could pass
    vacuously if the patch ever stopped working (e.g. a future refactor of
    `socket.socket`'s C-level binding). A real outbound `connect()` attempt
    (a made-up, non-routable address — nothing here waits on an actual
    network round trip) must still raise the same way."""
    with (
        pytest.raises(_NetworkAttempted),
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
    ):
        sock.connect(("203.0.113.1", 80))  # TEST-NET-3 (RFC 5737) — never routable
