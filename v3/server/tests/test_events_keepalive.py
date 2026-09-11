"""Issue #400: an idle /api/events stream sends a comment frame so a reverse
proxy's read timeout never cuts a quiet dashboard off."""

from __future__ import annotations

import pytest

from palaia_hub.events import bus as bus_module
from palaia_hub.events.bus import EventBus, _stream
from palaia_hub.events.schema import Envelope

pytestmark = pytest.mark.anyio


class _Request:
    def __init__(self, polls_before_disconnect: int) -> None:
        self._left = polls_before_disconnect

    async def is_disconnected(self) -> bool:
        self._left -= 1
        return self._left < 0


async def test_an_idle_stream_sends_keepalive_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bus_module, "SSE_KEEPALIVE_SECONDS", 0.0)
    bus = EventBus()
    initial = Envelope(event="hub.started", data={}, origin="hub")
    frames = [frame async for frame in _stream(_Request(2), bus, initial)]  # type: ignore[arg-type]
    assert frames[0].startswith("event: hub.started") or "hub.started" in frames[0]
    assert frames[1:] == [": keepalive\n\n", ": keepalive\n\n"]
    assert bus.subscriber_count == 0, "the stream unsubscribes on disconnect"


async def test_a_quiet_stream_within_the_interval_sends_nothing_extra() -> None:
    bus = EventBus()
    initial = Envelope(event="hub.started", data={}, origin="hub")
    frames = [frame async for frame in _stream(_Request(1), bus, initial)]  # type: ignore[arg-type]
    assert len(frames) == 1
