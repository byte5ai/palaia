"""Watcher: external change detection and checksum-based move detection."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from vault_helpers import EngineFactory, write_raw
from watchfiles import Change

from palaia_hub.vault import (
    ChangeEvent,
    EventBus,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
    VaultWatcher,
)
from palaia_hub.vault.watcher import is_vault_content

pytestmark = pytest.mark.anyio

#: SPEC-003 Q2 budget: an external edit must surface within ~2 s. Observed
#: watcher latency in the spike was 51-80 ms at a 200 ms debounce.
LATENCY_BUDGET_SECONDS = 2.0


class Collector:
    """Collects published events and lets a test await the next one."""

    def __init__(self) -> None:
        self.events: list[ChangeEvent] = []
        self.queue: asyncio.Queue[ChangeEvent] = asyncio.Queue()

    def __call__(self, event: ChangeEvent) -> None:
        self.events.append(event)
        self.queue.put_nowait(event)

    async def next_event(self, timeout: float = 5.0) -> ChangeEvent:
        return await asyncio.wait_for(self.queue.get(), timeout=timeout)

    async def drain(self, settle: float = 0.5) -> list[ChangeEvent]:
        await asyncio.sleep(settle)
        out: list[ChangeEvent] = []
        while not self.queue.empty():
            out.append(self.queue.get_nowait())
        return out


async def watched(make_engine: EngineFactory, debounce_ms: int = 100):
    bus = EventBus()
    collector = Collector()
    bus.subscribe(collector)
    engine = await make_engine("work", bus=bus)
    watcher = VaultWatcher(engine, debounce_ms=debounce_ms, step_ms=20)
    await watcher.start()
    await asyncio.sleep(0.3)  # let watchfiles establish its baseline snapshot
    return engine, watcher, collector


async def wait_until_watcher_settles(
    watcher: VaultWatcher, *, timeout: float = 10.0, quiet: float = 0.3
) -> None:
    """Poll ``watcher.stats.batches`` until it stops changing for ``quiet``
    seconds, or ``timeout`` elapses.

    A fixed sleep is exactly what made
    ``test_engine_writes_are_echoes_not_watcher_events`` flaky under
    full-suite CPU contention (#253): a delay generous enough on a quiet
    machine can still be shorter than the watcher's actual debounce + batch
    processing time once the event loop is starved of scheduling slices.
    Waiting for the batch counter to go quiet ties the wait to what the
    watcher actually did, not to a wall-clock guess — and ``stats.echoes``/
    ``stats.events`` are updated synchronously as part of processing each
    batch (before any ``await`` on an empty-events batch), so once
    ``batches`` has gone quiet those counters have already settled too.
    """
    deadline = time.monotonic() + timeout
    last_batches = watcher.stats.batches
    quiet_since = time.monotonic()
    while time.monotonic() < deadline:
        await asyncio.sleep(0.02)
        if watcher.stats.batches != last_batches:
            last_batches = watcher.stats.batches
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= quiet:
            return


# ----------------------------------------------------------------- integration


async def test_external_create_is_reported_within_the_debounce_budget(
    make_engine: EngineFactory,
) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        started = time.perf_counter()
        write_raw(engine, "notes/external.md", "---\ntitle: Ext\npermalink: notes/ext\n---\n\nhi\n")
        event = await collector.next_event()
        latency = time.perf_counter() - started
    finally:
        await watcher.stop()
    assert isinstance(event, NoteCreated)
    assert event.path == "notes/external.md"
    assert event.permalink == "notes/ext"
    assert event.external is True
    assert latency < LATENCY_BUDGET_SECONDS
    # The catalog learned about the note without an engine write.
    assert "notes/external.md" in engine.catalog


async def test_external_edit_is_reported_as_a_modification(make_engine: EngineFactory) -> None:
    engine = None
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/a", body="engine\n", title="A")
        await collector.drain()
        started = time.perf_counter()
        path = engine.root / "notes/a.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nhuman edit\n", encoding="utf-8")
        event = await collector.next_event()
        latency = time.perf_counter() - started
    finally:
        await watcher.stop()
    assert isinstance(event, NoteModified)
    assert event.external is True
    assert event.previous_checksum is not None
    assert event.checksum != event.previous_checksum
    assert latency < LATENCY_BUDGET_SECONDS


async def test_external_rename_is_detected_as_a_move_preserving_identity(
    make_engine: EngineFactory,
) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        created = await engine.write_note("notes/original", body="stable\n", title="Original")
        assert created.note is not None
        permalink = created.note.permalink
        await collector.drain()

        # Exactly what Obsidian does: a plain file rename. watchfiles reports
        # it as deleted(old) + added(new) in one debounce batch.
        (engine.root / "notes/original.md").rename(engine.root / "notes/renamed.md")
        events = [await collector.next_event()]
        events.extend(await collector.drain())
    finally:
        await watcher.stop()

    moves = [event for event in events if isinstance(event, NoteMoved)]
    assert len(moves) == 1, events
    assert moves[0].previous_path == "notes/original.md"
    assert moves[0].path == "notes/renamed.md"
    assert moves[0].permalink == permalink
    assert moves[0].external is True
    # No delete/create pair leaked through — that is what would lose history.
    assert not any(isinstance(event, NoteDeleted | NoteCreated) for event in events)
    assert engine.catalog["notes/renamed.md"].permalink == permalink
    assert watcher.stats.moves_detected == 1


async def test_external_delete_is_reported(make_engine: EngineFactory) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/a", body="x\n", title="A")
        await collector.drain()
        (engine.root / "notes/a.md").unlink()
        event = await collector.next_event()
    finally:
        await watcher.stop()
    assert isinstance(event, NoteDeleted)
    assert event.path == "notes/a.md"
    assert event.external is True
    assert "notes/a.md" not in engine.catalog


async def test_engine_writes_are_echoes_not_watcher_events(
    make_engine: EngineFactory,
) -> None:
    """The watcher must not re-publish the engine's own writes."""
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/a", body="x\n", title="A")
        await engine.edit_note(
            "notes/a",
            body="y\n",
            expected_checksum=(await engine.read_note("notes/a")).checksum,
        )
        # #253: wait for the watcher to actually finish processing the
        # resulting filesystem batch(es) instead of a fixed sleep, which a
        # busy machine can outrun (see wait_until_watcher_settles).
        await wait_until_watcher_settles(watcher)
        events = await collector.drain(settle=0.05)
    finally:
        await watcher.stop()
    # Only the engine's own (non-external) events reached the bus.
    assert [event.external for event in events] == [False, False]
    assert watcher.stats.events == 0
    assert watcher.stats.echoes >= 1


async def test_engine_private_paths_are_ignored(make_engine: EngineFactory) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        (engine.engine_dir / "index.db").write_text("scratch", encoding="utf-8")
        (engine.root / ".palaia-tmp-leftover.palaia-tmp").write_text("x", encoding="utf-8")
        events = await collector.drain(settle=0.8)
    finally:
        await watcher.stop()
    assert events == []


# ------------------------------------------------------------------- unit-level


async def test_process_batch_pairs_delete_and_add_by_checksum(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    created = await engine.write_note("notes/original", body="stable\n", title="Original")
    assert created.note is not None
    watcher = VaultWatcher(engine)

    source = engine.root / "notes/original.md"
    destination = engine.root / "notes/renamed.md"
    source.rename(destination)

    events = watcher.process_batch(
        [
            (Change.deleted, str(source)),
            (Change.added, str(destination)),
        ]
    )
    assert len(events) == 1
    move = events[0]
    assert isinstance(move, NoteMoved)
    assert move.previous_path == "notes/original.md"
    assert move.permalink == created.note.permalink


async def test_process_batch_does_not_pair_different_content(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="a\n", title="A")
    watcher = VaultWatcher(engine)
    write_raw(engine, "notes/b.md", "---\ntitle: B\npermalink: notes/b\n---\n\ndifferent\n")
    (engine.root / "notes/a.md").unlink()

    events = watcher.process_batch(
        [
            (Change.deleted, str(engine.root / "notes/a.md")),
            (Change.added, str(engine.root / "notes/b.md")),
        ]
    )
    kinds = sorted(type(event).__name__ for event in events)
    assert kinds == ["NoteCreated", "NoteDeleted"]


async def test_process_batch_folds_delete_plus_add_of_the_same_path(
    make_engine: EngineFactory,
) -> None:
    """An editor's save-as-rename over the same path is one modification."""
    engine = await make_engine("work")
    await engine.write_note("notes/a", body="a\n", title="A")
    watcher = VaultWatcher(engine)
    path = engine.root / "notes/a.md"
    path.write_text(path.read_text(encoding="utf-8") + "more\n", encoding="utf-8")

    events = watcher.process_batch([(Change.deleted, str(path)), (Change.added, str(path))])
    assert [type(event).__name__ for event in events] == ["NoteModified"]


def test_is_vault_content_filter(tmp_path: Path) -> None:
    root = tmp_path
    assert is_vault_content(root, root / "notes/a.md")
    assert not is_vault_content(root, root / ".git/index")
    assert not is_vault_content(root, root / ".palaia/index.db")
    assert not is_vault_content(root, root / ".obsidian/workspace.json")
    assert not is_vault_content(root, root / "notes/attachment.png")
    assert not is_vault_content(root, root / "notes/.a.md.x.palaia-tmp")


# ------------------------------------------------- issue #357: big drops, folders


async def test_batch_processing_runs_off_the_event_loop(make_engine: EngineFactory) -> None:
    """A slow batch (simulated: 0.6 s of blocking work) must not stall the
    loop — a heartbeat coroutine keeps ticking while it runs."""
    engine, watcher, collector = await watched(make_engine)
    try:
        original = watcher.process_batch

        def slow_batch(raw: object) -> list[ChangeEvent]:
            time.sleep(0.6)  # blocking on purpose: this is what used to run on the loop
            return original(raw)  # type: ignore[arg-type]

        watcher.process_batch = slow_batch  # type: ignore[method-assign]

        gaps: list[float] = []
        stop = asyncio.Event()

        async def heartbeat() -> None:
            last = time.monotonic()
            while not stop.is_set():
                await asyncio.sleep(0.02)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        beat = asyncio.create_task(heartbeat())
        write_raw(engine, "notes/slow.md", "---\ntitle: Slow\n---\nbody\n")
        event = await collector.next_event(timeout=5.0)
        stop.set()
        await beat
        assert isinstance(event, NoteCreated)
        assert max(gaps) < 0.3, f"event loop stalled for {max(gaps):.2f}s during batch processing"
    finally:
        await watcher.stop()


async def test_a_large_batch_is_coalesced_until_the_source_goes_quiet(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work")
    watcher = VaultWatcher(engine, coalesce_threshold=2, settle_ms=150, max_coalesce_ms=5000)
    queue: asyncio.Queue[set[tuple[Change, str]] | None] = asyncio.Queue()
    first = {(Change.added, "a.md"), (Change.added, "b.md")}
    queue.put_nowait({(Change.added, "c.md")})
    queue.put_nowait({(Change.deleted, "a.md"), (Change.added, "d.md")})

    merged = await watcher._coalesce(queue, first)

    assert merged == first | {
        (Change.added, "c.md"),
        (Change.deleted, "a.md"),
        (Change.added, "d.md"),
    }
    assert watcher.stats.coalesced == 2


async def test_a_small_batch_is_not_held_back(make_engine: EngineFactory) -> None:
    engine = await make_engine("work")
    watcher = VaultWatcher(engine, coalesce_threshold=20, settle_ms=2000)
    queue: asyncio.Queue[set[tuple[Change, str]] | None] = asyncio.Queue()
    started = time.monotonic()

    merged = await watcher._coalesce(queue, {(Change.added, "one.md")})

    assert merged == {(Change.added, "one.md")}
    assert time.monotonic() - started < 0.5
    assert watcher.stats.coalesced == 0


async def test_coalescing_stops_at_the_hard_deadline(make_engine: EngineFactory) -> None:
    """A source that never goes quiet still gets processed in slices."""
    engine = await make_engine("work")
    watcher = VaultWatcher(engine, coalesce_threshold=1, settle_ms=200, max_coalesce_ms=400)
    queue: asyncio.Queue[set[tuple[Change, str]] | None] = asyncio.Queue()

    async def trickle() -> None:
        for i in range(20):
            await asyncio.sleep(0.05)
            queue.put_nowait({(Change.added, f"n{i}.md")})

    feeder = asyncio.create_task(trickle())
    started = time.monotonic()
    merged = await watcher._coalesce(queue, {(Change.added, "first.md")})
    elapsed = time.monotonic() - started
    feeder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await feeder

    assert merged is not None and len(merged) >= 2
    assert 0.35 < elapsed < 1.5


async def test_a_folder_dropped_into_the_vault_arrives_as_one_pass(
    make_engine: EngineFactory, tmp_path: Path
) -> None:
    bus = EventBus()
    collector = Collector()
    bus.subscribe(collector)
    engine = await make_engine("work", bus=bus)
    watcher = VaultWatcher(
        engine, debounce_ms=100, step_ms=20, coalesce_threshold=20, settle_ms=300
    )
    await watcher.start()
    await asyncio.sleep(0.3)
    try:
        staging = tmp_path / "staging"
        staging.mkdir()
        for i in range(60):
            # Identified notes: a drop of notes *without* a permalink also
            # triggers identity assignment (issue #358), which is its own
            # pass and is covered by ``test_watcher_identity.py``.
            (staging / f"note-{i:02d}.md").write_text(
                f"---\ntitle: Note {i}\npermalink: notes/dropped/note-{i:02d}\n---\nbody {i}\n",
                encoding="utf-8",
            )
        import shutil

        shutil.copytree(staging, engine.root / "notes" / "dropped")

        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and len(collector.events) < 60:
            await asyncio.sleep(0.05)
        await wait_until_watcher_settles(watcher)

        assert len(collector.events) == 60
        assert all(isinstance(e, NoteCreated) for e in collector.events)
        assert watcher.stats.batches <= 3, watcher.stats
    finally:
        await watcher.stop()


async def test_a_renamed_folder_moves_every_note_it_held(make_engine: EngineFactory) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/team/alpha.md", body="alpha body", title="Alpha")
        await engine.write_note("notes/team/beta.md", body="beta body", title="Beta")
        await wait_until_watcher_settles(watcher)
        await collector.drain(0.1)
        collector.events.clear()  # the engine's own NoteCreated events, not the watcher's
        permalinks = {
            engine.catalog["notes/team/alpha.md"].permalink,
            engine.catalog["notes/team/beta.md"].permalink,
        }

        (engine.root / "notes" / "team").rename(engine.root / "notes" / "crew")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if len([e for e in collector.events if isinstance(e, NoteMoved)]) >= 2:
                break
            await asyncio.sleep(0.05)
        moves = [e for e in collector.events if isinstance(e, NoteMoved)]
        assert {(m.previous_path, m.path) for m in moves} == {
            ("notes/team/alpha.md", "notes/crew/alpha.md"),
            ("notes/team/beta.md", "notes/crew/beta.md"),
        }
        assert {m.permalink for m in moves} == permalinks
        assert "notes/team/alpha.md" not in engine.catalog
        assert engine.catalog["notes/crew/alpha.md"].permalink in permalinks
        assert watcher.stats.moves_detected == 2
    finally:
        await watcher.stop()


async def test_a_deleted_folder_deletes_every_note_it_held(make_engine: EngineFactory) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/old/one.md", body="one", title="One")
        await engine.write_note("notes/old/two.md", body="two", title="Two")
        await wait_until_watcher_settles(watcher)
        await collector.drain(0.1)
        collector.events.clear()  # the engine's own NoteCreated events, not the watcher's

        import shutil

        shutil.rmtree(engine.root / "notes" / "old")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if len([e for e in collector.events if isinstance(e, NoteDeleted)]) >= 2:
                break
            await asyncio.sleep(0.05)
        deletions = [e for e in collector.events if isinstance(e, NoteDeleted)]
        assert {d.path for d in deletions} == {"notes/old/one.md", "notes/old/two.md"}
        assert "notes/old/one.md" not in engine.catalog
        assert "notes/old/two.md" not in engine.catalog
    finally:
        await watcher.stop()
