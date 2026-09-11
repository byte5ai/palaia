"""The webhook delivery worker (SPEC-201 deliverable #2).

Two halves, both deliberately synchronous with the outbox rather than
in-memory: :meth:`HookDispatcher.on_event` — the hub event bus subscriber
(wired via :meth:`palaia_hub.events.bus.EventBus.on`) that turns a published
:class:`~palaia_hub.events.schema.Envelope` into one durable outbox row per
matching, enabled hook — and :meth:`HookDispatcher.deliver_due`, the worker
loop that actually POSTs. Splitting them means an event is never "lost in
flight": by the time ``on_event`` returns, every delivery it owes exists as
a committed SQLite row (:mod:`palaia_hub.hooks.outbox`), so a crash between
"event published" and "HTTP call sent" just means the next ``deliver_due``
picks the row back up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from ..events.schema import Envelope
from .outbox import HookOutbox, OutboxRow
from .signing import ATTEMPT_HEADER, EVENT_HEADER, EVENT_ID_HEADER, SIGNATURE_HEADER, sign
from .store import HookStore

logger = logging.getLogger("palaia_hub.hooks.delivery")

#: Deliverable #2: "dead-letter after N attempts".
DEFAULT_MAX_ATTEMPTS = 5
#: Exponential backoff base; capped so a long-broken receiver does not
#: starve the queue for everyone else for hours between checks.
_BASE_BACKOFF_SECONDS = 2.0
_MAX_BACKOFF_SECONDS = 300.0
_DELIVERY_TIMEOUT_SECONDS = 10.0


def _backoff_seconds(attempt: int) -> float:
    """``attempt`` is 1-indexed (the attempt that just failed)."""
    delay = _BASE_BACKOFF_SECONDS * float(2 ** (attempt - 1))
    return min(delay, _MAX_BACKOFF_SECONDS)


def _encode(envelope: Envelope) -> bytes:
    return json.dumps(envelope.to_json()).encode("utf-8")


class HookDispatcher:
    """Turns published events into durable outbox rows, then delivers them."""

    def __init__(
        self,
        store: HookStore,
        outbox: HookOutbox,
        *,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._store = store
        self._outbox = outbox
        self._client = client or httpx.AsyncClient(timeout=_DELIVERY_TIMEOUT_SECONDS)
        self._owns_client = client is None
        self._max_attempts = max_attempts

    # -------------------------------------------------------- event -> outbox

    def on_event(self, envelope: Envelope) -> None:
        """The in-process subscriber: enqueue one delivery per matching hook.

        Registered via ``event_bus.on(dispatcher.on_event)`` — see
        :mod:`palaia_hub.app`. Synchronous and cheap (one SQLite insert per
        matching hook): the actual network call happens later, in
        :meth:`deliver_due`, so a slow or unreachable receiver never delays
        the publisher.
        """
        payload = _encode(envelope)
        for hook in self._store.list_hooks(enabled_only=True):
            if not hook.matches(envelope.event):
                continue
            self._outbox.enqueue(
                hook_id=hook.id,
                event_id=envelope.id,
                event_name=envelope.event,
                payload=payload,
                signature=sign(hook.secret, payload),
            )

    # ------------------------------------------------------------- delivery

    async def deliver_due(self, *, limit: int = 20) -> int:
        """Attempt every currently-due delivery once; returns how many were tried."""
        rows = self._outbox.claim_due(limit=limit)
        for row in rows:
            await self._attempt(row)
        return len(rows)

    async def _attempt(self, row: OutboxRow) -> None:
        hook = self._store.get(row.hook_id)
        if hook is None or not hook.enabled:
            self._outbox.mark_dead(row.id, error="hook was removed or disabled")
            return
        attempt = row.attempts + 1
        try:
            response = await self._client.post(
                hook.url,
                content=row.payload,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: row.signature,
                    EVENT_HEADER: row.event_name,
                    EVENT_ID_HEADER: row.event_id,
                    ATTEMPT_HEADER: str(attempt),
                },
            )
        except httpx.HTTPError as exc:
            self._fail(row.id, attempt, error=f"request failed: {exc}")
            return
        if 200 <= response.status_code < 300:
            self._outbox.mark_delivered(row.id)
            return
        self._fail(row.id, attempt, error=f"HTTP {response.status_code}")

    def _fail(self, row_id: int, attempt: int, *, error: str) -> None:
        if attempt >= self._max_attempts:
            logger.warning("hook delivery dead-lettered after %d attempt(s): %s", attempt, error)
            self._outbox.mark_dead(row_id, error=error)
        else:
            logger.info("hook delivery failed (attempt %d), retrying: %s", attempt, error)
            self._outbox.mark_retry(row_id, delay_seconds=_backoff_seconds(attempt), error=error)

    async def run_forever(
        self, *, poll_seconds: float = 2.0, prune_every_seconds: float = 300.0
    ) -> None:
        """The background task :mod:`palaia_hub.app` starts in its lifespan.

        Also prunes the outbox's resolved rows on a slow cadence (issue
        #339) — once at start, then every ``prune_every_seconds``.
        """
        last_prune = float("-inf")
        while True:
            try:
                if time.monotonic() - last_prune >= prune_every_seconds:
                    self._outbox.prune()
                    last_prune = time.monotonic()
                delivered_any = await self.deliver_due()
                if not delivered_any:
                    await asyncio.sleep(poll_seconds)
            except Exception:  # noqa: BLE001 - the worker must survive anything
                logger.exception("hook delivery loop failed")
                await asyncio.sleep(poll_seconds)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


__all__ = ["DEFAULT_MAX_ATTEMPTS", "HookDispatcher"]
