"""Scheduling the curator: event-driven, with an interval fallback.

SPEC-206 deliverable #1: "event-driven via SPEC-201 (``inbox.captured``,
debounced) plus interval fallback". Both, because each covers the other's
blind spot — an event makes curation feel immediate, and the interval catches
a capture written straight into ``inbox/`` by hand (or by a client that
bypassed the ``capture`` tool), which no bus event ever announced.

Debouncing is what keeps a burst of captures from becoming a burst of
sessions: an agent that drops four captures in ten seconds should produce one
curation pass, not four overlapping ones. And an empty inbox costs one
catalog query per pass (:meth:`~palaia_hub.curator.runner.CuratorRunner.
run_once`), so the interval fallback on an idle hub is genuinely almost free.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping

from ..events.schema import Envelope
from .apply import ProposalApplier
from .models import ApplyReport, CuratorRunReport
from .runner import CuratorRunner

logger = logging.getLogger("palaia_hub.curator.service")

#: Seconds to wait after an ``inbox.captured`` event before curating, so a
#: burst of captures coalesces into one pass.
DEFAULT_DEBOUNCE_SECONDS = 30.0

#: Seconds between fallback passes when no event arrives.
DEFAULT_INTERVAL_SECONDS = 900.0


class CuratorScheduler:
    """Runs the curator (and the apply pass) on events and on a timer.

    Args:
        runners: one :class:`~palaia_hub.curator.runner.CuratorRunner` per
            vault key.
        appliers: one :class:`~palaia_hub.curator.apply.ProposalApplier` per
            vault key. Optional: a hub may want curation without an
            automatic apply pass, in which case approved proposals are
            applied by ``palaia-hub curator apply``.
        debounce_seconds / interval_seconds: see the module docstring.
        subscribe: the event bus's ``on()`` (``EventBus.on``), used to
            listen for ``inbox.captured``. Omitted, the scheduler is
            interval-only.
    """

    def __init__(
        self,
        runners: Mapping[str, CuratorRunner],
        *,
        appliers: Mapping[str, ProposalApplier] | None = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        subscribe: Callable[[Callable[[Envelope], None]], Callable[[], None]] | None = None,
    ) -> None:
        self._runners = dict(runners)
        self._appliers = dict(appliers or {})
        self._debounce = max(0.0, debounce_seconds)
        self._interval = max(1.0, interval_seconds)
        self._subscribe = subscribe
        self._unsubscribe: Callable[[], None] | None = None
        self._nudged = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        #: Passes completed since start — the handle tests wait on.
        self.passes = 0

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._subscribe is not None:
            self._unsubscribe = self._subscribe(self._on_event)
        self._task = asyncio.create_task(self._loop())

    async def aclose(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # ---------------------------------------------------------------- events

    def _on_event(self, envelope: Envelope) -> None:
        """Bus subscriber: an ``inbox.captured`` event nudges the next pass."""
        if envelope.event != "inbox.captured":
            return
        if envelope.data.get("duplicate"):
            # A duplicate capture wrote nothing, so there is nothing new to
            # curate — waking the curator for it would be pure cost.
            return
        self.nudge()

    def nudge(self) -> None:
        """Ask for a pass soon (debounced). Safe to call from a callback."""
        self._nudged.set()

    def add_vault(
        self,
        key: str,
        runner: CuratorRunner,
        applier: ProposalApplier | None = None,
    ) -> None:
        """Add a vault created at runtime (SPEC-301 deliverable #4).

        Safe to call between passes (:meth:`run_all` snapshots its own
        runner/applier lists before awaiting anything, so a vault added
        mid-pass is simply picked up starting the *next* pass, never a
        half-iterated one)."""
        self._runners[key] = runner
        if applier is not None:
            self._appliers[key] = applier

    # ------------------------------------------------------------------ loop

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._nudged.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            else:
                self._nudged.clear()
                if self._debounce:
                    await asyncio.sleep(self._debounce)
                self._nudged.clear()
            try:
                await self.run_all()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad pass must not kill the loop
                logger.exception("curator: scheduled pass failed")
            self.passes += 1

    async def run_all(self) -> tuple[list[CuratorRunReport], list[ApplyReport]]:
        """One pass: curate every vault's inbox, then apply what was approved."""
        runs: list[CuratorRunReport] = []
        applies: list[ApplyReport] = []
        # Snapshot both mappings before awaiting anything: `add_vault` can
        # be called from a different coroutine (a wizard-created vault,
        # SPEC-301) while a pass is in flight, and mutating a dict while
        # `.items()` iterates it raises `RuntimeError: dictionary changed
        # size during iteration` — a vault added mid-pass is simply first
        # curated on the *next* pass instead.
        for vault, runner in list(self._runners.items()):
            try:
                runs.append(await runner.run_once())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one vault must not stop the rest
                logger.exception("curator: run failed for vault %r", vault)
        for vault, applier in list(self._appliers.items()):
            try:
                applies.append(await applier.run_once())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one vault must not stop the rest
                logger.exception("curator: apply pass failed for vault %r", vault)
        return runs, applies


__all__ = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_INTERVAL_SECONDS",
    "CuratorScheduler",
]
