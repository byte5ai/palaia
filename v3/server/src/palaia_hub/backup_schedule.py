"""Backup **scheduling** (issue #438, the follow-up to #297): the interval.

Issue #297 asks for "a simple interval/retention setting, surfaced in the
dashboard; failures surface as events/notifications, never silently".
Retention shipped with the targets (each target's ``keep_last``); this
module is the interval, and the record the dashboard shows of what ran.

Two pieces, deliberately separate:

* :class:`BackupLedger` — the one way the *running hub* runs a target,
  shared by the scheduler and the dashboard's run action
  (``POST /api/backup/targets/{name}/run``). It owns one lock per target
  and remembers each target's last outcome.
* :class:`BackupScheduler` — a background task that asks the ledger to run
  every target, ``backup.interval_hours`` apart. Started and stopped with
  the hub (:func:`palaia_hub.app.create_app`'s lifespan), never a second
  daemon — the same posture as the curator's own timer.

**Never two runs of one target at once.** Archive names are stamped to the
second (:func:`palaia_hub.backup.archive_filename`), so a scheduled run and
a click on "Back up now" landing in the same second would both write the
same ``.part`` file. The per-target lock makes that impossible within this
process: a manual run that finds it held is answered "already running"
(409), and a scheduled pass that finds it held skips that target — the run
already in progress is producing the very backup the pass came for.
Scheduled passes themselves never overlap: the loop runs one pass to
completion before it computes when the next is due.

**The clock survives a restart.** A hub that restarts more often than its
interval — a daily auto-update and a 24-hour interval — would never reach
its first backup if the timer lived only in memory. So the start of every
scheduled pass is written to :data:`STATUS_FILENAME` in the hub home, and a
starting hub schedules its first pass for ``last pass + interval`` — or, if
that moment has already passed (or no pass ever ran), shortly after start
(:data:`DEFAULT_STARTUP_DELAY_SECONDS`), so a hub coming up is not also
building a full archive while it rebuilds its search indexes. The same file
keeps each target's last outcome, so the dashboard can say "last backup: 3 h
ago" after a restart too. It holds names, times, file names and failure
reasons — nothing from inside an archive, no secret.

**Failures never stop the timer.** A target that fails publishes
``backup.target.failed`` (:func:`palaia_hub.backup_targets.run_target`) and
the pass moves on to the next target; anything unexpected is logged and the
loop waits for the next interval, exactly like the curator's scheduled pass.

**Shutdown.** :meth:`BackupScheduler.aclose` cancels the waiting task. A
run already inside its worker thread cannot be interrupted from here and
finishes on its own; it is safe to be cut short by the process exiting all
the same — an archive is written under a ``.part`` name and renamed into
place only once complete, so a killed run never leaves a finished-looking
file behind.

**What the CLI does.** ``palaia-hub backup --target``/``--all-targets`` runs
in its own one-shot process: it takes none of these locks and records
nothing here (``--list-targets`` does *read* this file, to print the last
outcome). That is why the docs tell an operator who used to wrap it in
``cron``/``systemd`` to drop that wrapper once ``interval_hours`` is set —
two schedulers writing into one directory is the collision the lock exists
to prevent.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .backup_targets import BackupRun, BackupTarget, BackupTargetError, run_target
from .events.schema import HubEventHook
from .vault.atomic import atomic_write_bytes

logger = logging.getLogger("palaia_hub.backup_schedule")

#: The file in the hub home this module remembers runs in. Written with
#: :func:`palaia_hub.vault.atomic.atomic_write_bytes` (a ``0600`` temp file
#: renamed into place), so a reader never sees half of it.
STATUS_FILENAME = "backup-status.json"

#: The ``trigger`` a run started from the dashboard carries.
MANUAL_TRIGGER = "manual"
#: The ``trigger`` a run started by :class:`BackupScheduler` carries.
SCHEDULE_TRIGGER = "schedule"

#: How long after start the first pass waits when one is already due. Long
#: enough for a restarting hub to finish opening its vaults (index rebuilds
#: included) before a full archive competes with them for the disk.
DEFAULT_STARTUP_DELAY_SECONDS = 60.0

#: The longest single sleep of the scheduler's loop. It recomputes the time
#: left against the wall clock after each one, so a host that was suspended
#: or had its clock corrected is caught up within this long rather than
#: sleeping out a stale 24-hour ``asyncio.sleep``.
MAX_SLEEP_SECONDS = 300.0

_STATUS_VERSION = 1


class BackupTargetBusyError(BackupTargetError):
    """A run of this target is already in progress in this hub."""


@dataclasses.dataclass(frozen=True, slots=True)
class TargetRunRecord:
    """The last completed run of one target, as the dashboard shows it."""

    #: When the run finished, in seconds since the epoch.
    finished_at: float
    ok: bool
    #: :data:`MANUAL_TRIGGER` or :data:`SCHEDULE_TRIGGER`.
    trigger: str
    #: The archive this run produced (``None`` for a failed run).
    artifact: str | None = None
    bytes_written: int | None = None
    #: How many older archives retention deleted.
    pruned: int = 0
    duration_seconds: float | None = None
    #: The plain-language reason a failed run gives (``None`` on success).
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, raw: object) -> TargetRunRecord | None:
        """Read one persisted record back; ``None`` for anything malformed."""
        if not isinstance(raw, dict):
            return None
        try:
            return cls(
                finished_at=float(raw["finished_at"]),
                ok=bool(raw["ok"]),
                trigger=str(raw["trigger"]),
                artifact=_optional_str(raw.get("artifact")),
                bytes_written=_optional_int(raw.get("bytes_written")),
                pruned=int(raw.get("pruned") or 0),
                duration_seconds=_optional_float(raw.get("duration_seconds")),
                reason=_optional_str(raw.get("reason")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


class BackupLedger:
    """Runs this hub's backup targets one at a time each, and remembers how
    each run went. See the module docstring for why every run from the
    running hub goes through here.

    Thread-safe: :meth:`run` is called from worker threads (a backup is
    minutes of blocking filesystem work), the read methods from the event
    loop.
    """

    def __init__(
        self,
        home: Path,
        targets: Mapping[str, BackupTarget],
        *,
        publish: HubEventHook | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._home = home
        self._targets = dict(targets)
        self._publish = publish
        self._clock = clock
        self._run_locks = {name: threading.Lock() for name in self._targets}
        self._state_lock = threading.Lock()
        self._last_runs: dict[str, TargetRunRecord] = {}
        self._last_pass_at: float | None = None
        self._load()

    # ----------------------------------------------------------------- reads

    @property
    def path(self) -> Path:
        return self._home / STATUS_FILENAME

    @property
    def targets(self) -> Mapping[str, BackupTarget]:
        return self._targets

    @property
    def last_pass_at(self) -> float | None:
        """When the last scheduled pass started (epoch seconds), if ever."""
        with self._state_lock:
            return self._last_pass_at

    def last_run(self, name: str) -> TargetRunRecord | None:
        with self._state_lock:
            return self._last_runs.get(name)

    def is_running(self, name: str) -> bool:
        lock = self._run_locks.get(name)
        return lock is not None and lock.locked()

    def any_running(self) -> bool:
        return any(lock.locked() for lock in self._run_locks.values())

    # ---------------------------------------------------------------- writes

    def run(self, name: str, *, trigger: str) -> BackupRun:
        """Run target ``name`` once, now, in the calling thread.

        Raises :class:`BackupTargetBusyError` without touching the
        destination when a run of the same target is already in progress,
        and re-raises whatever the run itself raised after recording it.
        """
        target = self._targets[name]
        lock = self._run_locks[name]
        if not lock.acquire(blocking=False):
            raise BackupTargetBusyError(
                f"a backup to {name!r} is already being written by this hub. Wait for it "
                f"to finish — it is the backup you asked for."
            )
        try:
            try:
                run = run_target(target, self._home, publish=self._publish, trigger=trigger)
            except Exception as exc:
                self._record(
                    name,
                    TargetRunRecord(
                        finished_at=self._clock(), ok=False, trigger=trigger, reason=str(exc)
                    ),
                )
                raise
            self._record(
                name,
                TargetRunRecord(
                    finished_at=self._clock(),
                    ok=True,
                    trigger=trigger,
                    artifact=run.artifact,
                    bytes_written=run.bytes_written,
                    pruned=len(run.pruned),
                    duration_seconds=round(run.duration_seconds, 3),
                ),
            )
            return run
        finally:
            lock.release()

    def mark_pass(self, started_at: float) -> None:
        """Remember that a scheduled pass started at ``started_at``.

        Written *before* the pass runs, not after: a hub that dies mid-pass
        then does not start another full pass the moment it comes back.
        """
        with self._state_lock:
            self._last_pass_at = started_at
            self._save_locked()

    def _record(self, name: str, record: TargetRunRecord) -> None:
        with self._state_lock:
            self._last_runs[name] = record
            self._save_locked()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        """Read the status file, tolerating anything wrong with it.

        This file is a convenience — the schedule's clock and the
        dashboard's "last backup" line — never a record anything else relies
        on. A missing, unreadable or malformed file is therefore the state
        of a hub that has not run a backup yet, with a warning in the log,
        not a hub that refuses to start.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.warning("ignoring the unreadable backup status file %s: %s", self.path, exc)
            return
        if not isinstance(raw, dict):
            logger.warning("ignoring the malformed backup status file %s", self.path)
            return
        last_pass = raw.get("last_pass_at")
        if isinstance(last_pass, int | float) and not isinstance(last_pass, bool):
            self._last_pass_at = float(last_pass)
        targets = raw.get("targets")
        if isinstance(targets, dict):
            for name, entry in targets.items():
                # A target renamed or removed from config.yaml leaves its old
                # record behind in the file; it is simply not carried over.
                if name not in self._targets:
                    continue
                record = TargetRunRecord.from_json(entry)
                if record is not None:
                    self._last_runs[name] = record

    def _save_locked(self) -> None:
        document = {
            "version": _STATUS_VERSION,
            "last_pass_at": self._last_pass_at,
            "targets": {name: record.to_json() for name, record in self._last_runs.items()},
        }
        try:
            atomic_write_bytes(
                self.path, (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
            )
        except OSError as exc:
            # Losing this record costs a dashboard line and, at worst, one
            # early pass after a restart. Turning a backup that completed
            # into a reported failure over it would cost far more.
            logger.warning("could not write the backup status file %s: %s", self.path, exc)


class BackupScheduler:
    """Runs every configured target, ``interval_seconds`` apart, inside the
    hub. See the module docstring.

    Args:
        ledger: the same :class:`BackupLedger` the REST routes run through —
            the thing that keeps a scheduled and a manual run of one target
            from overlapping.
        interval_seconds: time between the *starts* of two passes.
            ``backup.interval_hours`` in ``config.yaml`` (at least an hour);
            any positive value is accepted here so tests need not wait.
        startup_delay_seconds: how soon after start a pass that is already
            due (or has never run) begins.
    """

    def __init__(
        self,
        ledger: BackupLedger,
        *,
        interval_seconds: float,
        startup_delay_seconds: float = DEFAULT_STARTUP_DELAY_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._ledger = ledger
        self._interval = float(interval_seconds)
        self._startup_delay = max(0.0, startup_delay_seconds)
        self._clock = clock
        self._task: asyncio.Task[None] | None = None
        self._next_run_at: float | None = None
        self._in_pass = False
        #: Passes completed since start — the handle tests wait on.
        self.passes = 0

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @property
    def next_run_at(self) -> float | None:
        """When the next pass is due (epoch seconds); ``None`` before
        :meth:`start` and while a pass is running."""
        return None if self._in_pass else self._next_run_at

    @property
    def running(self) -> bool:
        """Whether a scheduled pass is in progress right now."""
        return self._in_pass

    def status(self) -> dict[str, Any]:
        """The ``schedule`` block of ``GET /api/backup/targets``."""
        return {
            "interval_hours": round(self._interval / 3600, 4),
            "next_run_at": self.next_run_at,
            "last_pass_at": self._ledger.last_pass_at,
            "running": self.running,
        }

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._task is not None:
            return
        now = self._clock()
        earliest = now + self._startup_delay
        last = self._ledger.last_pass_at
        # Never run ahead of `last + interval`, never sooner than the start-up
        # delay — and a `last` in the future (a clock set back since) is
        # treated as "just ran", not as "due in however long".
        self._next_run_at = (
            earliest if last is None else max(earliest, min(last, now) + self._interval)
        )
        self._task = asyncio.create_task(self._loop(), name="palaia-backup-scheduler")

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._in_pass = False

    # ------------------------------------------------------------------ loop

    async def _loop(self) -> None:
        while True:
            await self._sleep_until_due()
            started = self._clock()
            self._in_pass = True
            try:
                await self.run_pass(started_at=started)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad pass must not kill the timer
                logger.exception("backup: scheduled pass failed")
            finally:
                self._in_pass = False
            self.passes += 1
            self._next_run_at = started + self._interval

    async def _sleep_until_due(self) -> None:
        while True:
            assert self._next_run_at is not None
            remaining = self._next_run_at - self._clock()
            if remaining <= 0:
                return
            await asyncio.sleep(min(remaining, MAX_SLEEP_SECONDS))

    async def run_pass(self, *, started_at: float | None = None) -> dict[str, bool]:
        """One pass: every target, one after another. Returns ``{name: ok}``
        for the targets it ran (a target skipped because it was busy is not
        in it).

        A failing target never stops the pass — the next one still runs,
        exactly like ``palaia-hub backup --all-targets``.
        """
        self._ledger.mark_pass(self._clock() if started_at is None else started_at)
        outcome: dict[str, bool] = {}
        for name in list(self._ledger.targets):
            try:
                await asyncio.to_thread(self._ledger.run, name, trigger=SCHEDULE_TRIGGER)
            except BackupTargetBusyError:
                logger.info("backup: %r is already being written; this pass skips it", name)
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - already published as backup.target.failed
                logger.warning("backup: scheduled run of %r failed: %s", name, exc)
                outcome[name] = False
                continue
            outcome[name] = True
        return outcome


__all__ = [
    "DEFAULT_STARTUP_DELAY_SECONDS",
    "MANUAL_TRIGGER",
    "MAX_SLEEP_SECONDS",
    "SCHEDULE_TRIGGER",
    "STATUS_FILENAME",
    "BackupLedger",
    "BackupScheduler",
    "BackupTargetBusyError",
    "TargetRunRecord",
]
