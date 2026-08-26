"""Periodic reachability probing for external servers (SPEC-302 #4).

Why a loop at all, rather than probing when someone asks: an upstream that
was down when the hub started, and comes back five minutes later, has to
start serving tools again *without* anybody clicking anything — and an
upstream that dies has to stop being offered before a model tries to call it
and waits out a timeout. Both are state changes nobody is watching for.

The loop is deliberately dumb: probe everything, publish
``gateway.upstream.up``/``down`` for whatever *changed*
(:class:`~palaia_hub.upstream.service.UpstreamService` owns that comparison),
and hand the changed keys to one callback — in production
:meth:`palaia_hub.gateway.dynamic.DynamicGateway.refresh_upstreams`, which
rebuilds only the profiles that mount them. Nothing here knows what a
profile is.

The first pass runs immediately on :meth:`UpstreamHealthMonitor.start`, in
the background: this is what mounts an upstream after a hub start that
deliberately mounted none (see ``DynamicGateway``'s ``upstream_service``
note — startup must not block on a network round-trip).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence

from .service import UpstreamService

logger = logging.getLogger("palaia_hub.upstream.monitor")

#: Seconds between probe passes. Human-paced: an external server coming back
#: within a minute is fast enough, and a shorter interval only adds traffic
#: to somebody else's service.
DEFAULT_PROBE_INTERVAL = 60.0

OnChange = Callable[[Sequence[str]], Awaitable[object]]


class UpstreamHealthMonitor:
    """Probes every configured upstream on an interval.

    Args:
        service: the registry to probe.
        on_change: awaited with the keys whose reachability changed since
            the previous pass (never with an empty list). Exceptions from it
            are logged, never propagated — a failed rebuild must not stop
            the monitor.
        interval: seconds between passes.
    """

    def __init__(
        self,
        service: UpstreamService,
        *,
        on_change: OnChange | None = None,
        interval: float = DEFAULT_PROBE_INTERVAL,
    ) -> None:
        self._service = service
        self._on_change = on_change
        self._interval = max(1.0, interval)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the loop (idempotent). Returns immediately — the first
        probe pass runs in the background."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        """Stop the loop and wait for the current pass to unwind."""
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def probe_once(self) -> list[str]:
        """One pass. Returns the keys whose ``up`` state changed."""
        before = {status.key: status.up for status in self._service.statuses()}
        unchecked = {
            status.key for status in self._service.statuses() if status.checked_at is None
        }
        await self._service.probe_all()
        after = {status.key: status.up for status in self._service.statuses()}
        changed = sorted(
            key
            for key, up in after.items()
            # A first-ever check counts as a change even when it confirms
            # "down": that is the pass that decides whether the profile
            # rebuild after hub startup mounts anything at all.
            if before.get(key) != up or key in unchecked
        )
        if changed and self._on_change is not None:
            try:
                await self._on_change(changed)
            except Exception as exc:  # noqa: BLE001 — a failed rebuild must not stop the loop
                logger.warning("reacting to an external-server change failed: %s", exc)
        return changed

    async def _run(self) -> None:
        while True:
            try:
                await self.probe_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the loop outlives one bad pass
                logger.warning("external-server health pass failed: %s", exc)
            await asyncio.sleep(self._interval)


__all__ = ["DEFAULT_PROBE_INTERVAL", "OnChange", "UpstreamHealthMonitor"]
