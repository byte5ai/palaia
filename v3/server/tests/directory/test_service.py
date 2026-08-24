"""``DirectoryService`` — event emission on every lifecycle transition
(SPEC-402 acceptance: "events fire on register/stale/deregister")."""

from __future__ import annotations

from typing import Any

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def service(clock: _Clock) -> DirectoryService:
    return DirectoryService(DirectoryStore(":memory:", clock=clock))


def _captured(service: DirectoryService) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    service.publish = lambda name, data: events.append((name, data))
    return events


@pytest.mark.anyio
async def test_register_emits_session_registered(service: DirectoryService) -> None:
    events = _captured(service)
    result = await service.register(scope="a", platform="claude-code")
    names = [e[0] for e in events]
    assert "session.registered" in names
    data = next(d for n, d in events if n == "session.registered")
    assert data["handle"] == result.session.handle
    assert "session_secret" not in data


@pytest.mark.anyio
async def test_stale_is_emitted_once_when_crossed(service: DirectoryService, clock: _Clock) -> None:
    result = await service.register(scope="a", ttl_seconds=60)
    events = _captured(service)
    clock.now += 61
    await service.list()
    stale_events = [e for e in events if e[0] == "session.stale"]
    assert len(stale_events) == 1
    assert stale_events[0][1]["handle"] == result.session.handle

    events.clear()
    await service.list()
    assert [e for e in events if e[0] == "session.stale"] == []


@pytest.mark.anyio
async def test_deregister_emits_session_deregistered(service: DirectoryService) -> None:
    result = await service.register(scope="a")
    events = _captured(service)
    await service.deregister(result.session.handle, result.session_secret)
    names = [e[0] for e in events]
    assert "session.deregistered" in names


@pytest.mark.anyio
async def test_deregister_already_gone_does_not_re_emit(service: DirectoryService) -> None:
    events = _captured(service)
    await service.deregister("no-such-handle", "whatever")
    assert [e for e in events if e[0] == "session.deregistered"] == []


@pytest.mark.anyio
async def test_update_to_idle_emits_session_idle_not_updated(service: DirectoryService) -> None:
    result = await service.register(scope="a")
    events = _captured(service)
    await service.update(result.session.handle, result.session_secret, status="idle")
    names = [e[0] for e in events]
    assert "session.idle" in names
    assert "session.updated" not in names


@pytest.mark.anyio
async def test_update_scope_emits_session_updated(service: DirectoryService) -> None:
    result = await service.register(scope="a")
    events = _captured(service)
    await service.update(result.session.handle, result.session_secret, scope="b")
    names = [e[0] for e in events]
    assert "session.updated" in names


@pytest.mark.anyio
async def test_no_publisher_wired_does_not_error(service: DirectoryService) -> None:
    # `publish` defaults to None — every operation must still work silently.
    result = await service.register(scope="a")
    await service.heartbeat(result.session.handle, result.session_secret)
    await service.deregister(result.session.handle, result.session_secret)
