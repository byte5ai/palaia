"""Async facade over :class:`DirectoryStore`, with ``session.*`` event
emission (SPEC-402 deliverable #2/#5).

The gateway tool family (:mod:`palaia_hub.gateway.directory_tools`) and the
REST mirror (:mod:`palaia_hub.directory_api`) both call this, not the store
directly — the one place that turns a synchronous, lock-guarded SQLite call
into an ``asyncio.to_thread`` call and publishes the resulting ``session.*``
event on the SPEC-201 bus. Same shape as
:mod:`palaia_hub.stash.service.StashService`: ``publish`` is any callable of
type :data:`Publisher`, so wiring in the real
:class:`palaia_hub.events.bus.EventBus` is a one-line change at the call
site, not here — and a caller with no bus at all still gets a fully working
directory, just silently.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

from .models import (
    DeregisterResult,
    HeartbeatResult,
    ListResult,
    QueryResult,
    RegisterResult,
    ReportedStatus,
    SessionRecord,
    SessionStatus,
    UpdateResult,
)
from .store import DEFAULT_TTL_SECONDS, DirectoryStore

Publisher = Callable[[str, dict[str, Any]], None]


def _session_data(session: SessionRecord) -> dict[str, Any]:
    """The event payload for one session — never the secret."""
    return {
        "handle": session.handle,
        "scope": session.scope,
        "host": session.host,
        "platform": session.platform,
        "agent_kind": session.agent_kind,
        "model": session.model,
        "status": session.status,
        "capabilities": list(session.capabilities),
    }


class DirectoryService:
    """Session directory operations, backing the ``directory_*`` tool
    family and the ``/api/directory`` REST mirror."""

    def __init__(self, store: DirectoryStore, *, publish: Publisher | None = None) -> None:
        self._store = store
        #: Public and reassignable, same reason as ``StashService.publish``:
        #: a caller that builds the service before it has an event bus in
        #: hand (see ``palaia_hub.app.create_app``) can wire one up after.
        self.publish = publish

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.publish is not None:
            self.publish(event_type, data)

    def _emit_stale(self, newly_stale: list[str]) -> None:
        for handle in newly_stale:
            self._emit("session.stale", {"handle": handle})

    async def register(
        self,
        *,
        scope: str = "",
        host: str = "",
        platform: str = "",
        agent_kind: str = "",
        model: str = "",
        capabilities: Sequence[str] = (),
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> RegisterResult:
        session, secret, newly_stale = await asyncio.to_thread(
            self._store.register,
            scope=scope,
            host=host,
            platform=platform,
            agent_kind=agent_kind,
            model=model,
            capabilities=capabilities,
            ttl_seconds=ttl_seconds,
        )
        self._emit("session.registered", _session_data(session))
        self._emit_stale(newly_stale)
        return RegisterResult(session=session, session_secret=secret)

    async def heartbeat(self, handle: str, session_secret: str) -> HeartbeatResult:
        session, newly_stale = await asyncio.to_thread(
            self._store.heartbeat, handle, session_secret
        )
        self._emit_stale(newly_stale)
        return HeartbeatResult(session=session)

    async def update(
        self,
        handle: str,
        session_secret: str,
        *,
        scope: str | None = None,
        status: ReportedStatus | None = None,
        capabilities: Sequence[str] | None = None,
    ) -> UpdateResult:
        session, newly_stale = await asyncio.to_thread(
            self._store.update,
            handle,
            session_secret,
            scope=scope,
            status=status,
            capabilities=capabilities,
        )
        if status == "idle":
            self._emit("session.idle", _session_data(session))
        else:
            self._emit("session.updated", _session_data(session))
        self._emit_stale(newly_stale)
        return UpdateResult(session=session)

    async def deregister(self, handle: str, session_secret: str) -> DeregisterResult:
        deregistered, newly_stale = await asyncio.to_thread(
            self._store.deregister, handle, session_secret
        )
        if deregistered:
            self._emit("session.deregistered", {"handle": handle})
        self._emit_stale(newly_stale)
        return DeregisterResult(handle=handle, deregistered=deregistered)

    async def list(
        self,
        *,
        status: SessionStatus | None = None,
        platform: str | None = None,
        capability: str | None = None,
    ) -> ListResult:
        sessions, newly_stale = await asyncio.to_thread(
            self._store.list, status=status, platform=platform, capability=capability
        )
        self._emit_stale(newly_stale)
        return ListResult(sessions=sessions)

    async def query(
        self, *, scope_contains: str | None = None, capability: str | None = None
    ) -> QueryResult:
        sessions, newly_stale = await asyncio.to_thread(
            self._store.query, scope_contains=scope_contains, capability=capability
        )
        self._emit_stale(newly_stale)
        return QueryResult(sessions=sessions)


__all__ = ["DirectoryService", "Publisher"]
