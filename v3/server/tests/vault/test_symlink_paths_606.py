"""Issue #606: no read or change of a note goes through a symbolic link.

A link inside a vault can lead anywhere on the server. The scan already
ignores links (issue #398); these tests pin that every path the engine
touches is refused *before* any filesystem access when part of it is a
link, so nothing outside the vault — and nothing inside it — changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from vault_helpers import EngineFactory

from palaia_hub.vault import InvalidPathError, NoteNotFoundError, VaultEngine

pytestmark = pytest.mark.anyio


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "theirs.md").write_text("---\ntitle: Theirs\n---\nnot ours\n", encoding="utf-8")
    return outside


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


async def _vault_with_link(tmp_path: Path, make_engine: EngineFactory) -> tuple[VaultEngine, Path]:
    outside = _outside(tmp_path)
    engine = await make_engine()
    await engine.write_note("notes/real.md", body="ours", title="Real")
    (engine.root / "escape").symlink_to(outside, target_is_directory=True)
    return engine, outside


async def test_a_write_into_a_linked_folder_is_refused_before_anything_is_written(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    engine, outside = await _vault_with_link(tmp_path, make_engine)
    before = _snapshot(outside)
    head = engine.git.head()
    catalog = set(engine.catalog)

    with pytest.raises(InvalidPathError, match="symbolic link 'escape'"):
        await engine.write_note("escape/escaped-note.md", body="evidence", title="Escaped")
    with pytest.raises(InvalidPathError, match="symbolic link 'escape'"):
        await engine.write_note("escape/deeper/still.md", body="evidence", title="Still")

    assert _snapshot(outside) == before
    assert engine.git.head() == head
    assert set(engine.catalog) == catalog


async def test_a_write_onto_a_note_that_is_itself_a_link_is_refused(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    outside = _outside(tmp_path)
    engine = await make_engine()
    (engine.root / "notes").mkdir()
    (engine.root / "notes" / "theirs.md").symlink_to(outside / "theirs.md")
    before = _snapshot(outside)

    with pytest.raises(InvalidPathError, match="symbolic link 'notes/theirs.md'"):
        await engine.write_note("notes/theirs.md", body="overwritten", title="Theirs")

    assert _snapshot(outside) == before
    assert (engine.root / "notes" / "theirs.md").is_symlink()


async def test_moving_a_note_into_a_linked_folder_is_refused_and_the_note_stays(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    engine, outside = await _vault_with_link(tmp_path, make_engine)
    before = _snapshot(outside)
    catalog = set(engine.catalog)

    with pytest.raises(InvalidPathError, match="symbolic link 'escape'"):
        await engine.move_note("notes/real.md", "escape/real.md")

    assert _snapshot(outside) == before
    assert (engine.root / "notes" / "real.md").read_text(encoding="utf-8").endswith("ours\n")
    assert set(engine.catalog) == catalog


async def test_listing_a_linked_folder_is_refused(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    engine, _outside_dir = await _vault_with_link(tmp_path, make_engine)

    with pytest.raises(InvalidPathError, match="symbolic link 'escape'"):
        await engine.list_dir("escape")
    with pytest.raises((InvalidPathError, NoteNotFoundError)):
        await engine.read_note("escape/theirs.md")


async def test_a_folder_swapped_for_a_link_after_open_is_refused_for_read_edit_move_and_delete(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    engine = await make_engine()
    await engine.write_note("notes/real.md", body="ours", title="Real")
    real = await engine.read_note("notes/real.md")
    # The catalogued folder is replaced by a link to a look-alike outside.
    (engine.root / "notes").rename(tmp_path / "moved-away")
    (outside / "real.md").write_text("---\ntitle: Real\n---\nnot ours\n", encoding="utf-8")
    (engine.root / "notes").symlink_to(outside, target_is_directory=True)
    before = _snapshot(outside)

    with pytest.raises(InvalidPathError, match="symbolic link 'notes'"):
        await engine.read_note("notes/real.md")
    with pytest.raises(InvalidPathError, match="symbolic link 'notes'"):
        await engine.edit_note("notes/real.md", body="changed", expected_checksum=real.checksum)
    with pytest.raises(InvalidPathError, match="symbolic link 'notes'"):
        await engine.move_note("notes/real.md", "elsewhere/real.md")
    with pytest.raises(InvalidPathError, match="symbolic link 'notes'"):
        await engine.delete_note("notes/real.md")

    assert _snapshot(outside) == before
    assert not (engine.root / "elsewhere").exists()


async def test_a_link_that_stays_inside_the_vault_is_refused_too(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine()
    await engine.write_note("notes/real.md", body="ours", title="Real")
    (engine.root / "alias-of-notes").symlink_to(engine.root / "notes", target_is_directory=True)

    with pytest.raises(InvalidPathError, match="symbolic link 'alias-of-notes'"):
        await engine.write_note("alias-of-notes/second.md", body="x", title="Second")

    assert not (engine.root / "notes" / "second.md").exists()


async def test_ordinary_nested_folders_still_work(make_engine: EngineFactory) -> None:
    engine = await make_engine()
    await engine.write_note("a/b/c/note.md", body="deep", title="Deep")
    await engine.move_note("a/b/c/note.md", "x/y/note.md")
    assert (await engine.read_note("x/y/note.md")).body.strip() == "deep"
    assert [entry.path for entry in await engine.list_dir("x/y")] == ["x/y/note.md"]
