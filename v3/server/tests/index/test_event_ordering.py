"""Issue #356: a deleted note cannot be resurrected by an older event.

The engine publishes events after it has released its own lock, so two
writers' events reach the index in either order — and the index applied
them concurrently: a modify's read-then-write around a delete's write put
the deleted note back into the index with no file behind it.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.vault import Note, NoteDeleted, NoteModified

pytestmark = pytest.mark.anyio


def _indexed_paths(index: Any) -> set[str]:
    return {entry.path for entry in index.index_entries()}


async def test_a_delete_is_not_overtaken_by_a_slower_earlier_modify(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "notes/doomed.md", body="soon gone\n", title="Doomed", frontmatter={"type": "note"}
    )
    assert "notes/doomed.md" in _indexed_paths(index)

    gate = threading.Event()
    real_upsert = index.writer.upsert_note

    def slow_upsert(note: Note) -> None:
        gate.wait(timeout=5)
        real_upsert(note)

    monkeypatch.setattr(index.writer, "upsert_note", slow_upsert)

    # Writer A's modify has read the note and is about to write it...
    modify = asyncio.create_task(
        index.apply_event(NoteModified(vault=engine.name, path="notes/doomed.md"))
    )
    await asyncio.sleep(0.1)
    # ...when writer B's delete arrives.
    delete = asyncio.create_task(
        index.apply_event(NoteDeleted(vault=engine.name, path="notes/doomed.md"))
    )
    await asyncio.sleep(0.1)
    gate.set()
    await asyncio.gather(modify, delete)

    assert "notes/doomed.md" not in _indexed_paths(index)


async def test_a_modify_for_a_note_that_is_already_gone_leaves_it_gone(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "notes/fleeting.md", body="here and gone\n", title="Fleeting", frontmatter={"type": "note"}
    )
    await engine.delete_note("notes/fleeting")
    assert "notes/fleeting.md" not in _indexed_paths(index)

    # The stale event is applied without an error, and changes nothing.
    await index.apply_event(NoteModified(vault=engine.name, path="notes/fleeting.md"))

    assert "notes/fleeting.md" not in _indexed_paths(index)
