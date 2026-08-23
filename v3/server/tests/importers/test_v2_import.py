"""Golden-fixture tests for the palaia v2 importer (SPEC-111)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from palaia_hub.importers import ImportRunner
from palaia_hub.importers.models import MappedNote, SkippedItem
from palaia_hub.importers.v2_source import find_store_root, iter_source_entries, map_v2_entry
from palaia_hub.vault import parse as vparse
from palaia_hub.vault.engine import VaultEngine
from palaia_hub.vault.models import Note

pytestmark = pytest.mark.anyio


async def _open(tmp_path: Path) -> VaultEngine:
    engine = VaultEngine(tmp_path / "vault", "work")
    await engine.open()
    return engine


def _mapped(store_root: Path) -> list[MappedNote | SkippedItem]:
    return [map_v2_entry(entry) for entry in iter_source_entries(store_root)]


async def _find_note(engine: VaultEngine, prefix: str) -> Note:
    await engine.refresh()
    for path, entry in engine.catalog.items():
        if path.startswith(prefix) and entry.permalink not in (None, "meta/vault"):
            return await engine.read_note(entry.permalink)  # type: ignore[arg-type]
    raise AssertionError(f"no note found under {prefix!r} (catalog: {sorted(engine.catalog)})")


def _assert_no_parse_warnings(note: Note) -> None:
    result = vparse.parse_note(note.text, note.path)
    assert result.warnings == (), (note.path, result.warnings)


async def test_dry_run_reports_counts_and_unmappable_reasons(
    tmp_path: Path, v2_store_fixture: Path
) -> None:
    engine = await _open(tmp_path)
    store_root = find_store_root(v2_store_fixture)
    runner = ImportRunner(engine)
    report = await runner.run("v2", str(store_root), _mapped(store_root), dry_run=True)

    assert report.dry_run is True
    assert report.created_count == 4  # memory, process, task, volatile-title memory
    assert report.unmappable_count == 2
    reasons = {item.source_path: item.reason for item in report.skipped}
    assert "id" in reasons["cold/no-id-entry.md"]
    assert "empty" in reasons["hot/f6666666-6666-4666-8666-666666666666.md"]

    # Dry run must not touch the vault: only the manifest exists.
    await engine.refresh()
    assert list(engine.catalog) == ["meta/vault.md"]


async def test_apply_creates_notes_with_expected_shape(
    tmp_path: Path, v2_store_fixture: Path
) -> None:
    engine = await _open(tmp_path)
    store_root = find_store_root(v2_store_fixture)
    runner = ImportRunner(engine)
    report = await runner.run("v2", str(store_root), _mapped(store_root), dry_run=False)

    assert report.created_count == 4
    assert report.unmappable_count == 2
    assert all(item.commit for item in report.items if item.outcome == "created")

    note = await _find_note(engine, "imported/v2/notes/rate-limit")
    assert note.frontmatter["type"] == "note"
    assert note.frontmatter["scope"] == "project"
    assert "infra" in note.frontmatter["tags"]
    imported_meta: dict[str, Any] = note.frontmatter["import"]
    assert imported_meta["tier"] == "hot"
    assert imported_meta["decay_seed"] == 1.0
    assert imported_meta["source"] == "palaia-v2"
    _assert_no_parse_warnings(note)

    process_note = await _find_note(engine, "imported/v2/processes/")
    assert process_note.frontmatter["type"] == "process"
    assert process_note.frontmatter["import"]["tier"] == "warm"
    _assert_no_parse_warnings(process_note)

    inbox_note = await _find_note(engine, "inbox/")
    assert inbox_note.frontmatter["type"] == "capture"
    assert inbox_note.frontmatter["status"] == "uncurated"
    assert "[entity]" in inbox_note.body
    assert "[why]" in inbox_note.body
    assert "in-progress" in inbox_note.body
    _assert_no_parse_warnings(inbox_note)

    volatile_note = await _find_note(engine, "imported/v2/notes/imported-v2-entry")
    assert volatile_note.title.startswith("Imported v2 entry")
    assert "[imported-title] Release v2026.5.7 notes" in volatile_note.body
    _assert_no_parse_warnings(volatile_note)


async def test_rerun_is_idempotent(tmp_path: Path, v2_store_fixture: Path) -> None:
    engine = await _open(tmp_path)
    store_root = find_store_root(v2_store_fixture)
    runner = ImportRunner(engine)

    first = await runner.run("v2", str(store_root), _mapped(store_root), dry_run=False)
    assert first.created_count == 4

    await engine.refresh()
    paths_after_first = set(engine.catalog)

    second = await runner.run("v2", str(store_root), _mapped(store_root), dry_run=False)
    assert second.created_count == 0
    assert second.already_imported_count == 4
    assert second.unmappable_count == 2

    await engine.refresh()
    assert set(engine.catalog) == paths_after_first
