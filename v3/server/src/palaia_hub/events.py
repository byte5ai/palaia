"""Minimal event bus + Server-Sent Events stream (SPEC-109).

The dashboard shell needs a live-state layer before SPEC-102's real vault
engine and event bus land — the two SPECs run in parallel on this package.
This module is deliberately self-contained: its own tiny in-process
pub/sub, and its own lightweight filesystem watcher for "a vault file
changed on disk". When SPEC-102's vault engine bus lands, it can publish
onto this same :class:`EventBus` (or this module's watcher can be retired
in favor of it) without changing the wire contract the web client already
speaks: each SSE frame is ``event: <type>`` / ``data: {"type", "data",
"ts"}``.

Two event types ship in this SPEC:

- ``health`` — a periodic snapshot, so the topbar's health badge and any
  other live indicator update without a page reload.
- ``vault_changed`` — emitted when a file under the watched directory
  (``PALAIA_WATCH_DIR``) is created, edited, moved or deleted. Debounced
  by ``watchfiles`` itself. Watching is opt-in: with no directory
  configured, the hub still starts and serves ``health`` events only —
  matching SPEC-101's "starts with zero config" rule.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

try:  # pragma: no cover - exercised indirectly; defensive only
    from watchfiles import awatch
except ImportError:  # pragma: no cover
    awatch = None  # type: ignore[assignment]

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

#: Directory to watch for vault changes. Unset (the default) disables
#: watching entirely — no error, just fewer event types on the stream.
WATCH_DIR_ENV = "PALAIA_WATCH_DIR"
#: Seconds between periodic health snapshots on the stream.
HEALTH_INTERVAL_ENV = "PALAIA_HEALTH_EVENT_INTERVAL_SECONDS"
DEFAULT_HEALTH_INTERVAL_SECONDS = 15.0

EventType = Literal["health", "vault_changed"]


@dataclasses.dataclass(frozen=True, slots=True)
class Event:
    """One item on the event stream."""

    type: EventType
    data: dict[str, Any]
    id: str = dataclasses.field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = dataclasses.field(default_factory=time.time)

    def to_sse(self) -> str:
        payload = json.dumps({"type": self.type, "data": self.data, "ts": self.ts})
        return f"id: {self.id}\nevent: {self.type}\ndata: {payload}\n\n"


class EventBus:
    """Tiny in-process pub/sub: one bounded queue per subscriber.

    A slow subscriber drops its oldest queued event rather than blocking
    the publisher (a UI tab left open for hours must never back-pressure
    the hub) — the next event on the bus still reaches it.
    """

    def __init__(self, *, max_queue: int = 64) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: Event) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


HealthSnapshot = Callable[[], dict[str, Any]]


async def _health_ticker(bus: EventBus, interval: float, snapshot: HealthSnapshot) -> None:
    while True:
        await asyncio.sleep(interval)
        bus.publish(Event(type="health", data=snapshot()))


async def _vault_watcher(bus: EventBus, path: str) -> None:
    if awatch is None:  # pragma: no cover - watchfiles always installed
        return
    async for changes in awatch(path):
        bus.publish(
            Event(
                type="vault_changed",
                data={
                    "count": len(changes),
                    "paths": sorted(str(changed_path) for _, changed_path in changes)[:20],
                },
            )
        )


def start_background_tasks(
    bus: EventBus, *, health_snapshot: HealthSnapshot
) -> list[asyncio.Task[None]]:
    """Start the health ticker and, if configured, the vault watcher.

    Returns the created tasks so the caller (the app's lifespan) can
    cancel them on shutdown.
    """
    interval = float(os.environ.get(HEALTH_INTERVAL_ENV, DEFAULT_HEALTH_INTERVAL_SECONDS))
    tasks = [asyncio.create_task(_health_ticker(bus, interval, health_snapshot))]

    watch_dir = os.environ.get(WATCH_DIR_ENV)
    if watch_dir and awatch is not None:
        tasks.append(asyncio.create_task(_vault_watcher(bus, watch_dir)))
    return tasks


async def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _stream(request: Request, bus: EventBus, initial: Event) -> AsyncIterator[str]:
    queue = bus.subscribe()
    try:
        yield initial.to_sse()
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            yield event.to_sse()
    finally:
        bus.unsubscribe(queue)


def build_events_router(bus: EventBus, *, health_snapshot: HealthSnapshot) -> APIRouter:
    """Build the ``/api/events`` router bound to ``bus``.

    A dedicated function (rather than a module-level router) keeps the
    bus instance and the health-snapshot callback out of module globals,
    so tests can build multiple independent apps in the same process.
    """
    router = APIRouter()

    @router.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        """Server-Sent Events stream: ``health`` + ``vault_changed``.

        Every connection first receives an immediate ``health`` snapshot
        (so a freshly opened dashboard tab does not wait out the first
        tick), then whatever the bus publishes afterwards.
        """
        initial = Event(type="health", data=health_snapshot())
        return StreamingResponse(
            _stream(request, bus, initial),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router


__all__ = [
    "DEFAULT_HEALTH_INTERVAL_SECONDS",
    "HEALTH_INTERVAL_ENV",
    "WATCH_DIR_ENV",
    "Event",
    "EventBus",
    "build_events_router",
    "start_background_tasks",
    "stop_background_tasks",
]
