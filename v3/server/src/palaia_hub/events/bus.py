"""The hub's one event bus + its Server-Sent Events transport (SPEC-201).

Supersedes the SPEC-109 stand-in of the same name: that module's own
docstring said this day would come — "When SPEC-102's vault engine bus
lands, it can publish onto this same EventBus... without changing the wire
contract the web client already speaks." This is that landing, with one
adjustment the unification forced: the wire contract's JSON body now
carries the public envelope (``event``, not ``type`` — see
:mod:`palaia_hub.events.schema`) instead of SPEC-109's ad hoc
``{"type", "data", "ts"}``. The dashboard's SSE client only ever read
``.data``/``.ts`` off that body (see ``v3/web/src/lib/events.ts``), so the
rename is invisible to it; what *does* change is which named frames it can
listen for — ``vault_changed`` is gone, replaced by the precise
``memory.entry.created|updated|deleted|moved`` names real vault events
carry (SPEC-201 acceptance: "do not leave two parallel event systems").

Three consumers, one bus:

1. **In-process subscription** (:meth:`EventBus.on`) — a plain callback,
   typed for the curator (SPEC-206) and, in this SPEC, for the webhook
   dispatcher (:mod:`palaia_hub.hooks.delivery`).
2. **SSE** (:meth:`EventBus.subscribe` + :func:`build_events_router`) — a
   bounded per-connection queue, unchanged in spirit from SPEC-109: a slow
   dashboard tab drops its oldest queued frame rather than back-pressuring
   the publisher.
3. **Webhooks** — layered entirely on top of consumer #1; see
   :mod:`palaia_hub.hooks`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .schema import Envelope, EventName

logger = logging.getLogger("palaia_hub.events.bus")

#: Seconds between periodic health snapshots on the stream. The SPEC-109
#: disk-watcher's own env var (``PALAIA_WATCH_DIR``) is retired along with
#: it — vault change events now arrive for real, from the vault registry's
#: bus (see :func:`palaia_hub.events.bridge.bridge_vault_events`), wired in
#: by :mod:`palaia_hub.app` whenever a ``vault_registry`` is given.
HEALTH_INTERVAL_ENV = "PALAIA_HEALTH_EVENT_INTERVAL_SECONDS"
DEFAULT_HEALTH_INTERVAL_SECONDS = 15.0

HealthSnapshot = Callable[[], dict[str, Any]]
Subscriber = Callable[[Envelope], None]


def publish_event(
    bus: EventBus,
    event: EventName | str,
    *,
    origin: str,
    data: dict[str, Any],
    vault: str | None = None,
    permalink: str | None = None,
) -> Envelope:
    """Build an :class:`Envelope` and publish it on ``bus`` in one call."""
    envelope = Envelope(event=event, data=data, origin=origin, vault=vault, permalink=permalink)
    bus.publish(envelope)
    return envelope


def publish_from_hook(
    bus: EventBus, event: EventName | str, data: dict[str, Any], *, origin: str
) -> Envelope:
    """Bridge a narrow ``(event_name, data)`` hook call onto the real bus.

    ``data`` may carry ``"vault"``/``"permalink"`` keys (see
    :data:`palaia_hub.events.schema.HubEventHook`); they are promoted to the
    envelope's own fields and left in ``data`` too, so a consumer reading
    only ``data`` still sees them.
    """
    return publish_event(
        bus,
        event,
        origin=origin,
        data=data,
        vault=data.get("vault"),
        permalink=data.get("permalink"),
    )


class EventBus:
    """The hub's one event bus: bounded SSE queues + plain callbacks.

    A slow SSE subscriber drops its oldest queued event rather than
    blocking the publisher (a UI tab left open for hours must never
    back-pressure the hub); a callback subscriber that raises is logged and
    skipped — never allowed to break the publisher, which by the time an
    event fires has usually already committed whatever it describes.
    """

    def __init__(self, *, max_queue: int = 64) -> None:
        self._queues: set[asyncio.Queue[Envelope]] = set()
        self._callbacks: list[Subscriber] = []
        self._max_queue = max_queue

    # ---------------------------------------------------------------- SSE

    def subscribe(self) -> asyncio.Queue[Envelope]:
        queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=self._max_queue)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Envelope]) -> None:
        self._queues.discard(queue)

    # ---------------------------------------------------------- in-process

    def on(self, callback: Subscriber) -> Callable[[], None]:
        """Register ``callback``; returns a callable that unsubscribes it.

        The typed in-process subscription API (SPEC-201 deliverable #4):
        the webhook dispatcher (:mod:`palaia_hub.hooks.delivery`) and,
        later, the curator (SPEC-206) both consume the bus this way.
        """
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._callbacks.remove(callback)

        return unsubscribe

    # -------------------------------------------------------------- publish

    def publish(self, envelope: Envelope) -> None:
        for queue in list(self._queues):
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(envelope)
        for callback in list(self._callbacks):
            try:
                callback(envelope)
            except Exception:  # noqa: BLE001 - a subscriber must not break a publish
                logger.exception("event subscriber failed", extra={"event": envelope.event})

    @property
    def subscriber_count(self) -> int:
        """SSE connections currently attached (queue-based subscribers only)."""
        return len(self._queues)


async def _health_ticker(bus: EventBus, interval: float, snapshot: HealthSnapshot) -> None:
    while True:
        await asyncio.sleep(interval)
        publish_event(bus, "health", origin="hub", data=snapshot())


def start_background_tasks(
    bus: EventBus, *, health_snapshot: HealthSnapshot
) -> list[asyncio.Task[None]]:
    """Start the health ticker. Returns the created tasks so the caller
    (the app's lifespan) can cancel them on shutdown."""
    interval = float(os.environ.get(HEALTH_INTERVAL_ENV, DEFAULT_HEALTH_INTERVAL_SECONDS))
    return [asyncio.create_task(_health_ticker(bus, interval, health_snapshot))]


async def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _stream(request: Request, bus: EventBus, initial: Envelope) -> AsyncIterator[str]:
    queue = bus.subscribe()
    try:
        yield initial.to_sse()
        while True:
            if await request.is_disconnected():
                break
            try:
                envelope = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            yield envelope.to_sse()
    finally:
        bus.unsubscribe(queue)


def build_events_router(bus: EventBus, *, health_snapshot: HealthSnapshot) -> APIRouter:
    """Build the ``/api/events`` router bound to ``bus``.

    A dedicated function (rather than a module-level router) keeps the bus
    instance and the health-snapshot callback out of module globals, so
    tests can build multiple independent apps in the same process.
    """
    router = APIRouter()

    @router.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        """Server-Sent Events stream carrying the public event envelope.

        Every connection first receives an immediate ``health`` snapshot
        (so a freshly opened dashboard tab does not wait out the first
        tick), then whatever the bus publishes afterwards.
        """
        initial = Envelope(event="health", data=health_snapshot(), origin="hub")
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
    "EventBus",
    "HealthSnapshot",
    "Subscriber",
    "build_events_router",
    "publish_event",
    "publish_from_hook",
    "start_background_tasks",
    "stop_background_tasks",
]
