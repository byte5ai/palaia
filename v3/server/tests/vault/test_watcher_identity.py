"""Issue #358: a note created outside the engine gets its identity.

Format spec §3.1 promises a permalink "assigned by the engine on first
index"; the engine had the operation, but nothing in production called it —
notes written in Obsidian stayed keyed by path and lost their relations on
the next external rename. The watcher now asks for it: once at start-up, and
whenever a batch reports a note without a permalink.
"""

from __future__ import annotations

import asyncio
import subprocess
import time

import pytest
from vault_helpers import EngineFactory, write_raw

from palaia_hub.vault import EventBus, VaultWatcher
from palaia_hub.vault import frontmatter as fm

pytestmark = pytest.mark.anyio

UNIDENTIFIED = "---\ntitle: Written In Obsidian\n---\n\nNo permalink here.\n"
MALFORMED = "---\ntitle: [unclosed\n---\n\nBroken frontmatter.\n"


async def _wait_for(predicate: object, *, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


def _permalink_on_disk(engine: object, relative: str) -> str | None:
    text = (engine.root / relative).read_text(encoding="utf-8")  # type: ignore[attr-defined]
    return fm.string_value(fm.parse(text).frontmatter, "permalink")[0] or None


async def test_a_note_that_arrives_while_watching_gets_a_permalink(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work", bus=EventBus())
    watcher = VaultWatcher(engine)
    await watcher.start()
    await asyncio.sleep(0.3)
    try:
        write_raw(engine, "notes/obsidian.md", UNIDENTIFIED)
        await _wait_for(lambda: _permalink_on_disk(engine, "notes/obsidian.md") is not None)
    finally:
        await watcher.stop()

    assert _permalink_on_disk(engine, "notes/obsidian.md") == "notes/written-in-obsidian"
    assert engine.catalog["notes/obsidian.md"].permalink == "notes/written-in-obsidian"
    assert watcher.stats.permalinks_assigned == 1
    subjects = subprocess.run(
        ["git", "-C", str(engine.root), "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "assign permalinks to 1 note(s)" in subjects


async def test_notes_that_arrived_while_nothing_watched_are_adopted_at_start(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine("work", bus=EventBus())
    write_raw(engine, "notes/offline.md", UNIDENTIFIED)
    await engine.refresh()  # what a hub start does: the catalog is built from files
    assert engine.catalog["notes/offline.md"].permalink is None

    watcher = VaultWatcher(engine)
    await watcher.start()
    try:
        assert _permalink_on_disk(engine, "notes/offline.md") == "notes/written-in-obsidian"
        assert watcher.stats.permalinks_assigned == 1
    finally:
        await watcher.stop()


async def test_a_malformed_note_is_left_exactly_as_written(make_engine: EngineFactory) -> None:
    engine = await make_engine("work", bus=EventBus())
    watcher = VaultWatcher(engine)
    await watcher.start()
    await asyncio.sleep(0.3)
    try:
        write_raw(engine, "notes/broken.md", MALFORMED)
        write_raw(engine, "notes/fine.md", UNIDENTIFIED)
        await _wait_for(lambda: _permalink_on_disk(engine, "notes/fine.md") is not None)
        await asyncio.sleep(0.5)
    finally:
        await watcher.stop()

    assert (engine.root / "notes/broken.md").read_text(encoding="utf-8") == MALFORMED
    assert watcher.stats.permalinks_assigned == 1
