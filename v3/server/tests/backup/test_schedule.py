"""Backup scheduling (issue #438): the interval half of #297's "a simple
interval/retention setting".

What is pinned here is what an operator relies on without watching: the
timer keeps running through failures, never writes one target twice at
once, and does not forget when it last ran just because the hub restarted.
"""

from __future__ import annotations

import asyncio
import json
import stat
import threading
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.backup_schedule import (
    MANUAL_TRIGGER,
    SCHEDULE_TRIGGER,
    STATUS_FILENAME,
    BackupLedger,
    BackupScheduler,
    BackupTargetBusyError,
)
from palaia_hub.backup_targets import (
    FAILED_EVENT,
    SUCCEEDED_EVENT,
    BackupTarget,
    BackupTargetError,
    build_targets,
)
from palaia_hub.config import BackupSettings, LocalDirectoryBackupTarget

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeTarget(BackupTarget):
    """A target that records its runs instead of building an archive."""

    kind = "fake"
    carries_full_archive = False
    secret_safe = False

    def __init__(
        self,
        *,
        name: str,
        fail: bool = False,
        explode: bool = False,
        gate: threading.Event | None = None,
    ) -> None:
        super().__init__(name=name)
        self.fail = fail
        self.explode = explode
        self.gate = gate
        self.started = threading.Event()
        self.runs = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self._counter = threading.Lock()

    @property
    def destination(self) -> str:
        return f"fake://{self.name}"

    def _write(self, home: Path) -> tuple[str, int, tuple[str, ...]]:
        with self._counter:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
        self.started.set()
        try:
            if self.gate is not None:
                assert self.gate.wait(timeout=10), "the test never opened the gate"
            self.runs += 1
            if self.explode:
                raise RuntimeError("an unexpected bug, not a destination failure")
            if self.fail:
                raise BackupTargetError(f"backup target {self.name!r}: the share is not mounted")
            return f"archive-{self.runs}.tar.gz", 42, ("old.tar.gz",)
        finally:
            with self._counter:
                self.concurrent -= 1


def _ledger(
    home: Path, *targets: BackupTarget, published: list[tuple[str, dict[str, Any]]] | None = None
) -> BackupLedger:
    return BackupLedger(
        home,
        {target.name: target for target in targets},
        publish=None if published is None else lambda e, d: published.append((e, d)),
    )


async def _wait_for(predicate: Any, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the scheduler")
        await asyncio.sleep(0.01)


# ------------------------------------------------------------------ the ledger


async def test_the_ledger_records_a_success_and_persists_it(tmp_path: Path) -> None:
    target = _FakeTarget(name="nas")
    published: list[tuple[str, dict[str, Any]]] = []
    ledger = _ledger(tmp_path, target, published=published)

    run = ledger.run("nas", trigger=MANUAL_TRIGGER)

    record = ledger.last_run("nas")
    assert record is not None
    assert (record.ok, record.trigger, record.artifact, record.bytes_written, record.pruned) == (
        True,
        MANUAL_TRIGGER,
        run.artifact,
        42,
        1,
    )
    assert published == [(SUCCEEDED_EVENT, {**run.to_json(), "trigger": MANUAL_TRIGGER})]
    # A fresh ledger over the same home — a restarted hub — still knows.
    reloaded = BackupLedger(tmp_path, {"nas": target}).last_run("nas")
    assert reloaded == record
    status_file = tmp_path / STATUS_FILENAME
    assert stat.S_IMODE(status_file.stat().st_mode) == 0o600


async def test_the_ledger_records_a_failure_and_re_raises_it(tmp_path: Path) -> None:
    published: list[tuple[str, dict[str, Any]]] = []
    ledger = _ledger(tmp_path, _FakeTarget(name="nas", fail=True), published=published)

    with pytest.raises(BackupTargetError):
        ledger.run("nas", trigger=SCHEDULE_TRIGGER)

    record = ledger.last_run("nas")
    assert record is not None
    assert record.ok is False
    assert "not mounted" in (record.reason or "")
    assert [(event, data["trigger"]) for event, data in published] == [
        (FAILED_EVENT, SCHEDULE_TRIGGER)
    ]


async def test_a_target_being_written_is_refused_a_second_writer(tmp_path: Path) -> None:
    gate = threading.Event()
    target = _FakeTarget(name="nas", gate=gate)
    ledger = _ledger(tmp_path, target)
    first = threading.Thread(target=ledger.run, args=("nas",), kwargs={"trigger": "schedule"})
    first.start()
    assert target.started.wait(timeout=10)

    assert ledger.is_running("nas")
    with pytest.raises(BackupTargetBusyError):
        ledger.run("nas", trigger=MANUAL_TRIGGER)
    gate.set()
    first.join(timeout=10)

    assert target.runs == 1
    assert not ledger.is_running("nas")


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"targets": {"nas": "nope"}}'])
async def test_a_damaged_status_file_is_a_hub_that_has_not_backed_up_yet(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / STATUS_FILENAME).write_text(content, encoding="utf-8")

    ledger = _ledger(tmp_path, _FakeTarget(name="nas"))

    assert ledger.last_run("nas") is None
    assert ledger.last_pass_at is None


async def test_a_removed_target_s_old_record_is_not_carried_over(tmp_path: Path) -> None:
    _ledger(tmp_path, _FakeTarget(name="old")).run("old", trigger=MANUAL_TRIGGER)

    ledger = _ledger(tmp_path, _FakeTarget(name="nas"))
    ledger.mark_pass(123.0)

    saved = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert saved["targets"] == {}
    assert saved["last_pass_at"] == 123.0


async def test_building_a_ledger_writes_nothing(tmp_path: Path) -> None:
    _ledger(tmp_path, _FakeTarget(name="nas"))

    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------- the scheduler


async def test_the_schedule_runs_every_target_again_and_again(tmp_path: Path) -> None:
    first, second = _FakeTarget(name="nas"), _FakeTarget(name="usb")
    ledger = _ledger(tmp_path, first, second)
    scheduler = BackupScheduler(ledger, interval_seconds=0.05, startup_delay_seconds=0)

    await scheduler.start()
    try:
        await _wait_for(lambda: scheduler.passes >= 3)
    finally:
        await scheduler.aclose()

    assert first.runs >= 3
    assert second.runs >= 3
    record = ledger.last_run("usb")
    assert record is not None
    assert record.trigger == SCHEDULE_TRIGGER
    assert ledger.last_pass_at is not None


async def test_a_failing_target_neither_stops_the_pass_nor_the_timer(tmp_path: Path) -> None:
    """Issue #297: failures are surfaced, never silent — and never fatal
    to the schedule. The broken share is reported every pass; the working
    disk after it still gets its backup every pass."""
    broken = _FakeTarget(name="share", fail=True)
    buggy = _FakeTarget(name="buggy", explode=True)
    working = _FakeTarget(name="disk")
    published: list[tuple[str, dict[str, Any]]] = []
    ledger = _ledger(tmp_path, broken, buggy, working, published=published)
    scheduler = BackupScheduler(ledger, interval_seconds=0.05, startup_delay_seconds=0)

    await scheduler.start()
    try:
        await _wait_for(lambda: scheduler.passes >= 2)
    finally:
        await scheduler.aclose()

    assert working.runs >= 2
    failed = [data["target"] for event, data in published if event == FAILED_EVENT]
    assert failed.count("share") >= 2
    assert failed.count("buggy") >= 2
    share_record = ledger.last_run("share")
    assert share_record is not None
    assert share_record.ok is False


async def test_a_pass_that_raises_does_not_kill_the_timer(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, _FakeTarget(name="nas"))
    scheduler = BackupScheduler(ledger, interval_seconds=0.05, startup_delay_seconds=0)
    calls = 0
    real_run_pass = scheduler.run_pass

    async def flaky_pass(*, started_at: float | None = None) -> dict[str, bool]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("the status file's disk vanished")
        return await real_run_pass(started_at=started_at)

    scheduler.run_pass = flaky_pass  # type: ignore[method-assign]
    await scheduler.start()
    try:
        await _wait_for(lambda: scheduler.passes >= 3)
    finally:
        await scheduler.aclose()

    assert calls >= 3


async def test_passes_never_overlap_even_when_one_outlasts_the_interval(tmp_path: Path) -> None:
    gate = threading.Event()
    slow = _FakeTarget(name="nas", gate=gate)
    ledger = _ledger(tmp_path, slow)
    scheduler = BackupScheduler(ledger, interval_seconds=0.01, startup_delay_seconds=0)

    await scheduler.start()
    try:
        await _wait_for(slow.started.is_set)
        assert scheduler.running
        assert scheduler.next_run_at is None
        # Many intervals pass while the first run is still writing…
        await asyncio.sleep(0.2)
        assert scheduler.passes == 0
        gate.set()
        await _wait_for(lambda: scheduler.passes >= 3)
    finally:
        await scheduler.aclose()

    # …and no second run of the target ever started beside it.
    assert slow.max_concurrent == 1


async def test_a_scheduled_pass_skips_a_target_a_manual_run_is_writing(tmp_path: Path) -> None:
    gate = threading.Event()
    target = _FakeTarget(name="nas", gate=gate)
    ledger = _ledger(tmp_path, target)
    manual = threading.Thread(target=ledger.run, args=("nas",), kwargs={"trigger": "manual"})
    manual.start()
    assert target.started.wait(timeout=10)
    scheduler = BackupScheduler(ledger, interval_seconds=3600, startup_delay_seconds=0)

    outcome = await scheduler.run_pass()

    gate.set()
    manual.join(timeout=10)
    assert outcome == {}
    assert target.runs == 1
    assert target.max_concurrent == 1


async def test_a_restarted_hub_keeps_the_clock(tmp_path: Path) -> None:
    """A hub that restarts more often than its interval must not start the
    interval over each time — nor run a pass on every start."""
    now = 1_000_000.0
    ledger = _ledger(tmp_path, _FakeTarget(name="nas"))
    ledger.mark_pass(now - 3600)  # the last pass started an hour ago

    restarted = BackupLedger(tmp_path, ledger.targets)
    scheduler = BackupScheduler(
        restarted, interval_seconds=6 * 3600, startup_delay_seconds=60, clock=lambda: now
    )
    await scheduler.start()
    try:
        assert scheduler.next_run_at == now - 3600 + 6 * 3600
    finally:
        await scheduler.aclose()


async def test_an_overdue_or_first_ever_pass_waits_out_the_start_up_delay(
    tmp_path: Path,
) -> None:
    now = 1_000_000.0
    never = BackupScheduler(
        _ledger(tmp_path / "a", _FakeTarget(name="nas")),
        interval_seconds=3600,
        startup_delay_seconds=60,
        clock=lambda: now,
    )
    overdue_ledger = _ledger(tmp_path / "b", _FakeTarget(name="nas"))
    overdue_ledger.mark_pass(now - 10 * 3600)
    overdue = BackupScheduler(
        overdue_ledger, interval_seconds=3600, startup_delay_seconds=60, clock=lambda: now
    )
    future_ledger = _ledger(tmp_path / "c", _FakeTarget(name="nas"))
    future_ledger.mark_pass(now + 10 * 3600)  # the clock was set back since
    future = BackupScheduler(
        future_ledger, interval_seconds=3600, startup_delay_seconds=60, clock=lambda: now
    )

    for scheduler in (never, overdue, future):
        await scheduler.start()
    try:
        assert never.next_run_at == now + 60
        assert overdue.next_run_at == now + 60
        assert future.next_run_at == now + 3600
    finally:
        for scheduler in (never, overdue, future):
            await scheduler.aclose()


async def test_the_pass_start_is_written_before_the_pass_runs(tmp_path: Path) -> None:
    """A hub that dies mid-pass must not start another full pass the moment
    it comes back up."""
    gate = threading.Event()
    target = _FakeTarget(name="nas", gate=gate)
    ledger = _ledger(tmp_path, target)
    scheduler = BackupScheduler(ledger, interval_seconds=3600, startup_delay_seconds=0)

    pass_task = asyncio.create_task(scheduler.run_pass(started_at=555.0))
    await _wait_for(target.started.is_set)
    saved = json.loads((tmp_path / STATUS_FILENAME).read_text(encoding="utf-8"))
    gate.set()
    await pass_task

    assert saved["last_pass_at"] == 555.0


async def test_the_schedule_writes_real_archives_with_retention(tmp_path: Path) -> None:
    """End to end over the real local-directory target: the schedule is
    just another caller of the same run, retention included."""
    home = tmp_path / "home"
    (home / "vaults" / "work").mkdir(parents=True)
    (home / "vaults" / "work" / "note.md").write_text("# Hi\n", encoding="utf-8")
    destination = tmp_path / "backups"
    destination.mkdir()
    for stamp in ("20200101T000000Z", "20200102T000000Z"):
        (destination / f"palaia-backup-{stamp}.tar.gz").write_bytes(b"old")
    settings = BackupSettings(
        interval_hours=1,
        targets=[LocalDirectoryBackupTarget(name="nas", path=str(destination), keep_last=2)],
    )
    ledger = BackupLedger(home, build_targets(settings))
    scheduler = BackupScheduler(ledger, interval_seconds=3600, startup_delay_seconds=0)

    await scheduler.start()
    try:
        await _wait_for(lambda: scheduler.passes >= 1)
    finally:
        await scheduler.aclose()

    archives = sorted(path.name for path in destination.glob("palaia-backup-*.tar.gz"))
    assert len(archives) == 2
    assert "palaia-backup-20200101T000000Z.tar.gz" not in archives
    record = ledger.last_run("nas")
    assert record is not None
    assert record.ok
    assert record.artifact in archives
    assert record.pruned == 1


async def test_stopping_the_scheduler_stops_the_timer(tmp_path: Path) -> None:
    target = _FakeTarget(name="nas")
    scheduler = BackupScheduler(
        _ledger(tmp_path, target), interval_seconds=0.05, startup_delay_seconds=0
    )
    await scheduler.start()
    await _wait_for(lambda: scheduler.passes >= 1)

    await scheduler.aclose()
    runs = target.runs
    await asyncio.sleep(0.2)

    assert target.runs == runs


async def test_the_interval_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BackupScheduler(_ledger(tmp_path, _FakeTarget(name="nas")), interval_seconds=0)
