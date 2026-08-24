"""Async facade over :class:`StashStore`, with ``stash.*`` event emission.

The gateway tool family (:mod:`palaia_hub.gateway.stash_tools`) and the REST
mirror (:mod:`palaia_hub.stash_api`) both call this, not the store directly
— it is the one place that turns a synchronous, lock-guarded SQLite call
into an ``asyncio.to_thread`` call and publishes the resulting ``stash.*``
event (deliverable #4: "Emits ``stash.*`` events on the SPEC-201 bus (if
merged; else the internal bus stub)"). SPEC-201 has not merged as of this
SPEC — :mod:`palaia_hub.events`'s :class:`EventBus` is that internal stub;
``publish`` here is any callable of that shape, so swapping in the real bus
later is a one-line change at the call site, not here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from .models import DelResult, GetResult, ListResult, SetResult, StashEntry, StatusResult
from .store import StashStore

#: ``publish(event_type, data)`` — matches
#: ``lambda t, d: bus.publish(Event(type=t, data=d))`` for
#: :class:`palaia_hub.events.EventBus`. ``None`` (the default) means no bus
#: is wired up; every stash operation still works, just silently.
Publisher = Callable[[str, dict[str, Any]], None]


class StashService:
    """Namespaced cache operations, backing the stash tool family."""

    def __init__(self, store: StashStore, *, publish: Publisher | None = None) -> None:
        self._store = store
        #: Public and reassignable so a caller that builds the service
        #: before it has an event bus in hand (see ``palaia_hub.app.
        #: create_app``) can wire one up afterwards, not just at
        #: construction time.
        self.publish = publish

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.publish is not None:
            self.publish(event_type, data)

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None = None,
        stale_after_seconds: float | None = None,
    ) -> SetResult:
        size_bytes, evicted = await asyncio.to_thread(
            self._store.set,
            namespace,
            key,
            value,
            ttl_seconds=ttl_seconds,
            stale_after_seconds=stale_after_seconds,
        )
        self._emit(
            "stash.set",
            {"namespace": namespace, "key": key, "size_bytes": size_bytes, "evicted": evicted},
        )
        for label in evicted:
            evicted_namespace, _, evicted_key = label.partition("/")
            self._emit("stash.evicted", {"namespace": evicted_namespace, "key": evicted_key})
        return SetResult(namespace=namespace, key=key, size_bytes=size_bytes, evicted=evicted)

    async def get(self, namespace: str, key: str) -> GetResult:
        entry: StashEntry | None = await asyncio.to_thread(self._store.get, namespace, key)
        self._emit("stash.get", {"namespace": namespace, "key": key, "found": entry is not None})
        return GetResult(namespace=namespace, key=key, found=entry is not None, entry=entry)

    async def delete(self, namespace: str, key: str) -> DelResult:
        deleted = await asyncio.to_thread(self._store.delete, namespace, key)
        self._emit("stash.del", {"namespace": namespace, "key": key, "deleted": deleted})
        return DelResult(namespace=namespace, key=key, deleted=deleted)

    async def list(self, namespace: str) -> ListResult:
        entries = await asyncio.to_thread(self._store.list, namespace)
        return ListResult(namespace=namespace, entries=entries)

    async def status(self) -> StatusResult:
        total_entries, total_bytes, namespaces = await asyncio.to_thread(self._store.status)
        return StatusResult(
            total_entries=total_entries,
            total_bytes=total_bytes,
            budget_bytes=self._store.total_budget_bytes,
            namespaces=namespaces,
        )


__all__ = ["Publisher", "StashService"]
