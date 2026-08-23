"""Golden-fixture tests for the basic-memory importer (SPEC-111)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.importers import ImportRunner
from palaia_hub.importers.basic_memory_source import iter_source_entries, map_bm_entry
from palaia_hub.importers.models import MappedNote, SkippedItem
from palaia_hub.vault import parse as vparse
from palaia_hub.vault.engine import VaultEngine
from palaia_hub.vault.models import Note

pytestmark = pytest.mark.anyio


async def _open(tmp_path: Path) -> VaultEngine:
    engine = VaultEngine(tmp_path / "vault", "work")
    await engine.open()
    return engine


def _mapped(vault_root: Path) -> list[MappedNote | SkippedItem]:
    return [map_bm_entry(entry) for entry in iter_source_entries(vault_root)]


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
    tmp_path: Path, bm_vault_fixture: Path
) -> None:
    engine = await _open(tmp_path)
    runner = ImportRunner(engine)
    report = await runner.run(
        "basic-memory", str(bm_vault_fixture), _mapped(bm_vault_fixture), dry_run=True
    )

    assert report.dry_run is True
    # api-gateway, release-2026-5-7, onboarding-checklist -> 3 mappable notes.
    assert report.created_count == 3
    assert report.unmappable_count == 2
    reasons = {item.source_path: item.reason for item in report.skipped}
    assert "attachment" in reasons["assets/diagram.png"]
    assert "unparseable" in reasons["notes/broken-frontmatter.md"]

    await engine.refresh()
    assert list(engine.catalog) == ["meta/vault.md"]


async def test_apply_maps_observations_relations_and_permalinks(
    tmp_path: Path, bm_vault_fixture: Path
) -> None:
    engine = await _open(tmp_path)
    runner = ImportRunner(engine)
    report = await runner.run(
        "basic-memory", str(bm_vault_fixture), _mapped(bm_vault_fixture), dry_run=False
    )
    assert report.created_count == 3
    assert report.unmappable_count == 2

    gateway = await _find_note(engine, "imported/basic-memory/api-gateway")
    assert gateway.frontmatter["type"] == "note"
    assert gateway.frontmatter["aliases"] == ["projects/api-gateway"]
    assert gateway.frontmatter["import"]["source_permalink"] == "projects/api-gateway"
    # explicit category and relation lines pass through unchanged
    assert "- [rate-limit] 100 req/min ^rate-limit" in gateway.body
    assert "- relates_to [[Pricing]]" in gateway.body
    assert "- [[Curator]]" in gateway.body
    # the bare bullet gained an explicit [note] category
    assert "- [note] Bumped the connection pool size after the incident." in gateway.body
    # code fence and blockquote survive untouched
    assert "- this bullet is inside a code fence and must stay untouched" in gateway.body
    assert "> A quoted note from the incident review" in gateway.body
    _assert_no_parse_warnings(gateway)

    release = await _find_note(engine, "imported/basic-memory/imported-basic-memory-note")
    assert release.title.startswith("Imported basic-memory note")
    assert "[imported-title] OpenClaw 2026.5.7 release notes" in release.body
    assert release.frontmatter.get("schema") == "release-notes"
    _assert_no_parse_warnings(release)

    onboarding = await _find_note(engine, "imported/basic-memory/onboarding-checklist")
    assert onboarding.frontmatter["type"] == "process"
    assert "- [ ] Send the welcome packet" in onboarding.body
    assert "- [x] Schedule the kickoff call" in onboarding.body
    assert (
        "- [note] Provision the shared workspace and confirm access." in onboarding.body
    )
    _assert_no_parse_warnings(onboarding)


async def test_rerun_is_idempotent(tmp_path: Path, bm_vault_fixture: Path) -> None:
    engine = await _open(tmp_path)
    runner = ImportRunner(engine)

    first = await runner.run(
        "basic-memory", str(bm_vault_fixture), _mapped(bm_vault_fixture), dry_run=False
    )
    assert first.created_count == 3

    await engine.refresh()
    paths_after_first = set(engine.catalog)

    second = await runner.run(
        "basic-memory", str(bm_vault_fixture), _mapped(bm_vault_fixture), dry_run=False
    )
    assert second.created_count == 0
    assert second.already_imported_count == 3

    await engine.refresh()
    assert set(engine.catalog) == paths_after_first
