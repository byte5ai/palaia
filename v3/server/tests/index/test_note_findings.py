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
import threading
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


async def _current(index: Any, path: str) -> list[str]:
    return [finding.code for finding in await index.current_note_findings(path)]


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

    async def verify_while_a_note_changes(stop: object = None) -> list[Finding]:
        await index.apply_event(NoteDeleted(vault=engine.name, path="notes/a.md"))
        return [stale, kept]

    monkeypatch.setattr(index._doctor, "verify_notes", verify_while_a_note_changes)
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
    assert "permalink-duplicate" not in await _current(index, "notes/one.md")


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

    async def never_finishes(stop: object = None) -> list[Finding]:
        started.set()
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(index._doctor, "verify_notes", never_finishes)
    index.start_findings_scan()
    await started.wait()
    await index.close()
    assert index._findings_task is None


async def test_a_failing_scan_leaves_the_index_serving(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, index = await open_index(tmp_path / "vault")

    async def explodes(stop: object = None) -> list[Finding]:
        raise RuntimeError("doctor exploded")

    monkeypatch.setattr(index._doctor, "verify_notes", explodes)
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


async def test_a_duplicate_permalink_is_reported_whichever_claimant_it_resolves_to(
    tmp_path: Path, open_index: Any
) -> None:
    """The doctor files the finding under one claimant only; a read by the
    permalink lands on whichever the catalog resolves it to."""
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", "---\ntitle: One\npermalink: notes/same\n---\n\n1\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    await engine.refresh()
    await index.refresh_note_findings()

    for path in ("notes/one.md", "notes/two.md"):
        assert "permalink-duplicate" in _codes(index, path), path
    service = EngineVaultService(engine, index)
    assert "permalink-duplicate" in [hit.code for hit in await service.note_findings("notes/same")]


async def test_only_the_duplicate_finding_is_shared_between_claimants(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", b"---\ntitle: One\npermalink: notes/same\n---\n\ncaf\xe9\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    await engine.refresh()
    await index.refresh_note_findings()
    assert "not-utf8" in _codes(index, "notes/one.md")
    assert "not-utf8" not in _codes(index, "notes/two.md")


RENAMED_TARGET = "---\ntitle: New Name\npermalink: notes/old-name\n---\n\nrenamed\n"
LINKING_NOTE = "---\ntitle: Linker\npermalink: notes/linker\n---\n\nSee [[Old Name]].\n"


async def test_a_link_fixed_on_the_target_side_is_no_longer_reported(
    tmp_path: Path, open_index: Any
) -> None:
    """Adding the old name as an alias on the renamed note repairs the link
    without touching the note that holds it — no event names that note."""
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/old-name.md", RENAMED_TARGET)
    _write(engine.root, "notes/linker.md", LINKING_NOTE)
    await engine.refresh()
    await index.refresh_note_findings()
    assert "partial-rename" in await _current(index, "notes/linker.md")

    _write(
        engine.root,
        "notes/old-name.md",
        RENAMED_TARGET.replace("title: New Name\n", "title: New Name\naliases: [Old Name]\n"),
    )
    await engine.refresh()
    assert "partial-rename" not in await _current(index, "notes/linker.md")
    assert index.note_findings("notes/linker.md") == (), "the cache forgets it too"


async def test_a_permalink_changed_in_an_editor_resolves_the_duplicate(
    tmp_path: Path, open_index: Any
) -> None:
    """The watcher reports an external frontmatter edit as a plain
    modification of the *other* note."""
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", "---\ntitle: One\npermalink: notes/same\n---\n\n1\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    await engine.refresh()
    await index.refresh_note_findings()

    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/two\n---\n\n2\n")
    await engine.refresh()
    await index.apply_event(NoteModified(vault=engine.name, path="notes/two.md"))
    assert "permalink-duplicate" not in await _current(index, "notes/one.md")


async def test_an_unrelated_delete_keeps_a_duplicate_reported(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", "---\ntitle: One\npermalink: notes/same\n---\n\n1\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    _write(engine.root, "notes/other.md", "---\ntitle: Other\npermalink: notes/other\n---\n\nx\n")
    await engine.refresh()
    await index.refresh_note_findings()

    (engine.root / "notes/other.md").unlink()
    await engine.refresh()
    await index.apply_event(NoteDeleted(vault=engine.name, path="notes/other.md"))
    assert "permalink-duplicate" in await _current(index, "notes/one.md")


async def test_a_note_without_a_permalink_is_found_by_the_reference_it_was_read_by(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/bare.md", b"---\ntitle: Bare\n---\n\ncaf\xe9\n")
    await engine.refresh()
    await index.refresh_note_findings()

    service = EngineVaultService(engine, index)
    note = await service.read("notes/bare.md")
    codes = [hit.code for hit in await service.note_findings("notes/bare.md")]
    assert "not-utf8" in codes, note.permalink


async def test_each_claimant_reports_only_its_own_findings_when_read_by_title(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/one.md", b"---\ntitle: One\npermalink: notes/same\n---\n\ncaf\xe9\n")
    _write(engine.root, "notes/two.md", "---\ntitle: Two\npermalink: notes/same\n---\n\n2\n")
    await engine.refresh()
    await index.refresh_note_findings()

    service = EngineVaultService(engine, index)
    two = [hit.code for hit in await service.note_findings("Two")]
    assert "permalink-duplicate" in two
    assert "not-utf8" not in two, "notes/one.md's encoding problem is not notes/two.md's"


async def test_a_set_stop_ends_the_file_walk(tmp_path: Path, open_index: Any) -> None:
    """``close()`` sets the stop event, because cancelling the task cannot
    stop the thread the doctor's walk runs in."""
    engine, index = await open_index(tmp_path / "vault")
    _write(engine.root, "notes/latin.md", LATIN1_NOTE)
    await engine.refresh()
    stop = threading.Event()
    stop.set()
    codes = [f.code for f in await index._doctor.verify_notes(stop)]
    assert "not-utf8" not in codes
