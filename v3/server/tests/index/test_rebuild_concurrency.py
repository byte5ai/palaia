"""Issue #332: a full rebuild must not lose what happens while it runs.

A rebuild is one transaction over the index's single connection. Before the
fix, a change event arriving mid-rebuild was applied straight into that
transaction: ``finish()`` then deleted the freshly indexed note as "stale"
(it was not in the catalog snapshot the rebuild walked), and the event's own
``commit()`` committed whatever half of the rebuild had run so far — the
all-or-nothing promise the writer documents was not kept. An exception inside
the walk left the transaction open for the next writer to commit.

Now events are held back and replayed after the rebuild, every other commit
on the connection joins the rebuild while it is open, and a failing rebuild
rolls back to the previous index.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.index.graph import GraphReader
from palaia_hub.vault import Note, VaultEngine

pytestmark = pytest.mark.anyio


def _indexed_paths(index: Any) -> set[str]:
    return {entry.path for entry in index.index_entries()}


def _slow_reader(engine: VaultEngine, *, per_note: float) -> Any:
    original = engine.read_note_at

    def read(relative: str) -> Note:
        time.sleep(per_note)
        return original(relative)

    return read


async def test_a_note_written_during_a_rebuild_is_indexed_not_dropped(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, index = await open_index(golden_work_vault)
    before = _indexed_paths(index)
    monkeypatch.setattr(engine, "read_note_at", _slow_reader(engine, per_note=0.03))

    rebuild = asyncio.create_task(index.reindex())
    await asyncio.sleep(0.1)
    assert index.db.rebuilding, "the rebuild should still be in flight"
    result = await engine.write_note(
        "notes/during-rebuild",
        body="Written while the index was rebuilding.\n",
        title="During Rebuild",
    )
    assert result.commit is not None
    await rebuild

    assert not index.db.conn.in_transaction
    assert _indexed_paths(index) == before | {"notes/during-rebuild.md"}
    hits = await index.search("rebuilding", mode="fts", limit=5)
    assert "notes/during-rebuild" in {hit.permalink for hit in hits.hits}


async def test_a_failing_rebuild_rolls_back_and_the_index_stays_usable(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, index = await open_index(golden_work_vault)
    before = _indexed_paths(index)
    assert len(before) > 3
    original = engine.read_note_at
    calls = {"n": 0}

    def failing(relative: str) -> Note:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk hiccup mid-rebuild")
        return original(relative)

    monkeypatch.setattr(engine, "read_note_at", failing)
    with pytest.raises(RuntimeError, match="hiccup"):
        await index.reindex()

    # Rolled back: no open transaction for the next writer to commit, and
    # the previous index is intact.
    assert not index.db.conn.in_transaction
    assert not index.db.rebuilding
    assert _indexed_paths(index) == before

    # The index keeps working incrementally ...
    await engine.write_note("notes/after-failure", body="still indexed\n", title="After")
    assert "notes/after-failure.md" in _indexed_paths(index)
    assert not index.db.conn.in_transaction

    # ... and the next rebuild succeeds.
    monkeypatch.setattr(engine, "read_note_at", original)
    assert await index.reindex() == len(before) + 1
    assert _indexed_paths(index) == before | {"notes/after-failure.md"}


async def test_a_note_deleted_during_a_rebuild_is_skipped_not_fatal(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, index = await open_index(golden_work_vault)
    paths = sorted(engine.catalog)
    victim = paths[-1]
    original = engine.read_note_at

    def read(relative: str) -> Note:
        if relative == paths[0]:
            # Between the catalog snapshot and this read, the file vanishes.
            (engine.root / victim).unlink()
        return original(relative)

    monkeypatch.setattr(engine, "read_note_at", read)
    count = await index.reindex()

    assert count == len(paths) - 1
    assert victim not in _indexed_paths(index)
    assert not index.db.conn.in_transaction


async def test_other_writers_cannot_commit_half_a_rebuild(
    golden_work_vault: Path, open_index: Any
) -> None:
    """Metadata writes and recall's access counter used to call ``commit()``
    on the shared connection; inside a rebuild that committed the partial
    transaction. They now join it — and roll back with it."""
    _, index = await open_index(golden_work_vault)
    db = index.db
    graph = GraphReader(db)

    db.begin_rebuild()
    try:
        db.meta_set("probe", "during-rebuild")
        graph.record_access(["projects/api-gateway"], at="2026-09-05T00:00:00Z")
        assert db.conn.in_transaction, "a commit slipped through the rebuild"
    finally:
        db.end_rebuild(commit=False)

    assert not db.conn.in_transaction
    assert db.meta_get("probe") is None
    assert graph.access(["projects/api-gateway"])["projects/api-gateway"].hits == 0

    # Outside a rebuild the same calls commit as they always did.
    db.meta_set("probe", "after")
    assert db.meta_get("probe") == "after"


async def test_concurrent_rebuild_requests_are_serialised(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two overlapping ``reindex()`` calls (a rename event during a dashboard
    rebuild, say) must not interleave ``begin``/``emit`` on one writer."""
    engine, index = await open_index(golden_work_vault)
    before = _indexed_paths(index)
    monkeypatch.setattr(engine, "read_note_at", _slow_reader(engine, per_note=0.01))

    counts = await asyncio.gather(index.reindex(), index.reindex(), index.reindex())

    assert set(counts) == {len(before)}
    assert _indexed_paths(index) == before
    assert not index.db.conn.in_transaction
