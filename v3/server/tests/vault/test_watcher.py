"""Watcher: external change detection and checksum-based move detection."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from conftest import EngineFactory, write_raw
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


async def test_engine_writes_are_not_reported_as_external(make_engine: EngineFactory) -> None:
    engine, watcher, collector = await watched(make_engine)
    try:
        await engine.write_note("notes/a", body="x\n", title="A")
        events = await collector.drain(settle=0.8)
    finally:
        await watcher.stop()
    watcher_events = [event for event in events if event.external]
    assert watcher_events == []


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

    events = watcher.process_batch(
        [(Change.deleted, str(path)), (Change.added, str(path))]
    )
    assert [type(event).__name__ for event in events] == ["NoteModified"]


def test_is_vault_content_filter(tmp_path: Path) -> None:
    root = tmp_path
    assert is_vault_content(root, root / "notes/a.md")
    assert not is_vault_content(root, root / ".git/index")
    assert not is_vault_content(root, root / ".palaia/index.db")
    assert not is_vault_content(root, root / ".obsidian/workspace.json")
    assert not is_vault_content(root, root / "notes/attachment.png")
    assert not is_vault_content(root, root / "notes/.a.md.x.palaia-tmp")
