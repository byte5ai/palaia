"""The per-note doctor findings the index keeps for the nudge layer (issue #440).

The index runs the vault doctor's file-side checks once in the background and
keeps what they found about single notes, so ``read`` can pass it to the
nudge layer without scanning anything per call. The property under test is
the one that makes that safe: the table only ever *loses* findings between
scans — an event that touches a note drops what was known about it, and a
scan never reports a note that changed while it ran.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import Finding, NoteDeleted, NoteModified

pytestmark = pytest.mark.anyio

LATIN1_NOTE = b"---\ntitle: Latin\npermalink: notes/latin\n---\n\ncaf\xe9\n"


def _write(root: Path, relative: str, data: bytes | str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _codes(index: Any, path: str) -> list[str]:
    return [finding.code for finding in index.note_findings(path)]


async def test_a_scan_keeps_findings_by_note(tmp_path: Path, open_index: Any) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/latin.md", LATIN1_NOTE)
    _write(engine.root, "notes/fine.md", "---\ntitle: Fine\npermalink: notes/fine\n---\n\nok\n")
    await engine.refresh()

    assert index.note_findings("notes/latin.md") == (), "nothing is known before a scan"
    assert await index.refresh_note_findings() >= 1
    assert "not-utf8" in _codes(index, "notes/latin.md")
    assert index.note_findings("notes/fine.md") == ()


async def test_a_change_to_a_note_drops_what_was_known_about_it(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/latin.md", LATIN1_NOTE)
    await engine.refresh()
    await index.refresh_note_findings()
    assert "not-utf8" in _codes(index, "notes/latin.md")

    # The owner converted the file; the watcher reports the change.
    _write(engine.root, "notes/latin.md", LATIN1_NOTE.decode("latin-1"))
    await engine.refresh()
    await index.apply_event(NoteModified(vault=engine.name, path="notes/latin.md"))
    assert index.note_findings("notes/latin.md") == ()


async def test_a_note_that_changed_during_a_scan_is_not_reported(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scan read the file before or after the change — either way its
    finding about it describes a version that may no longer exist."""
    engine, index = await open_index(tmp_path / "vault")
    stale = Finding(
        code="partial-rename", severity="warning", detail="d", fix="f", path="notes/a.md", line=3
    )
    kept = Finding(code="not-utf8", severity="warning", detail="d", fix="f", path="notes/b.md")

    async def verify_while_a_note_changes(index_view: object = None) -> list[Finding]:
        await index.apply_event(NoteDeleted(vault=engine.name, path="notes/a.md"))
        return [stale, kept]

    monkeypatch.setattr(index._doctor, "verify", verify_while_a_note_changes)
    await index.refresh_note_findings()
    assert index.note_findings("notes/a.md") == ()
    assert _codes(index, "notes/b.md") == ["not-utf8"]


async def test_deleting_one_claimant_clears_a_duplicate_permalink_finding(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", "---\ntitle: One\npermalink: notes/same\n---\n\n1\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    await engine.refresh()
    await index.refresh_note_findings()
    assert "permalink-duplicate" in _codes(index, "notes/one.md")

    # The duplicate is resolved by removing the *other* note, which the
    # finding does not sit on.
    (engine.root / "notes/two.md").unlink()
    await engine.refresh()
    await index.apply_event(NoteDeleted(vault=engine.name, path="notes/two.md"))
    assert "permalink-duplicate" not in _codes(index, "notes/one.md")


async def test_the_background_scan_fills_the_table(tmp_path: Path, open_index: Any) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/latin.md", LATIN1_NOTE)
    await engine.refresh()
    index.start_findings_scan()
    assert index._findings_task is not None
    await index._findings_task
    assert "not-utf8" in _codes(index, "notes/latin.md")


async def test_closing_the_index_stops_a_running_scan(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, index = await open_index(tmp_path / "vault")
    started = asyncio.Event()

    async def never_finishes(index_view: object = None) -> list[Finding]:
        started.set()
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(index._doctor, "verify", never_finishes)
    index.start_findings_scan()
    await started.wait()
    await index.close()
    assert index._findings_task is None


async def test_a_failing_scan_leaves_the_index_serving(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, index = await open_index(tmp_path / "vault")

    async def explodes(index_view: object = None) -> list[Finding]:
        raise RuntimeError("doctor exploded")

    monkeypatch.setattr(index._doctor, "verify", explodes)
    index.start_findings_scan()
    assert index._findings_task is not None
    await index._findings_task  # logged, not raised
    assert index.note_findings("notes/a.md") == ()


async def test_the_vault_service_answers_by_permalink(tmp_path: Path, open_index: Any) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/latin.md", LATIN1_NOTE)
    await engine.refresh()
    await index.refresh_note_findings()

    service = EngineVaultService(engine, index)
    assert [hit.code for hit in await service.note_findings("notes/latin")] == ["not-utf8"]
    assert await service.note_findings("notes/unknown") == []
    assert await EngineVaultService(engine).note_findings("notes/latin") == [], (
        "without an index nothing was scanned"
    )
