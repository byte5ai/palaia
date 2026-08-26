"""The index is disposable: drop it, rebuild it, get the same answers.

Format spec §10 and SPEC-104's first acceptance criterion. The query battery
is SPEC-113's (``tests/e2e/query_battery.py``) so this check and the e2e
rebuild scenario are asking the same question of the same corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.index import SearchFilters, VaultIndex
from palaia_hub.vault import VaultDoctor

sys.path.insert(0, str(Path(__file__).parent.parent / "e2e"))

from query_battery import CANONICAL_QUERIES, MUST_INCLUDE, NO_MATCH_QUERY  # noqa: E402

pytestmark = pytest.mark.anyio


async def _battery(index: VaultIndex) -> dict[str, list[tuple[str, str]]]:
    """Run the battery, keeping ranked order and the addressed ref per hit."""
    out: dict[str, list[tuple[str, str]]] = {}
    for query in CANONICAL_QUERIES:
        results = await index.search(query, mode="fts", limit=100)
        out[query] = [(hit.permalink, hit.ref) for hit in results.hits]
    return out


async def test_drop_database_then_reindex_reproduces_identical_results(
    golden_work_vault: Path, open_index: Any, tmp_path: Path
) -> None:
    db_path = tmp_path / "index.sqlite3"
    engine, index = await open_index(golden_work_vault, index_path=db_path)
    before = await _battery(index)
    assert any(before[query] for query in CANONICAL_QUERIES), "battery must not be all-empty"
    assert before[NO_MATCH_QUERY] == []
    await index.close()

    # "Delete the DB": the file and its WAL sidecars, exactly as a user
    # clearing a broken index would.
    db_path.unlink()
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    assert not db_path.exists()

    rebuilt = VaultIndex(engine, path=db_path)
    await rebuilt.open(start_worker=False)
    try:
        after = await _battery(rebuilt)
        assert after == before
    finally:
        await rebuilt.close()


async def test_must_include_queries_find_their_notes(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    for query, expected in MUST_INCLUDE.items():
        if query == "marathon":  # personal vault, not this one
            continue
        results = await index.search(query, mode="fts", limit=20)
        found = {hit.permalink for hit in results.hits}
        assert set(expected) <= found, f"{query!r} lost {set(expected) - found}"


async def test_forward_reference_query_finds_the_referencing_note(
    golden_work_vault: Path, open_index: Any
) -> None:
    """"Q3 Roadmap" names no entity — the note referencing it is still findable."""
    _, index = await open_index(golden_work_vault)
    results = await index.search("Q3 Roadmap", mode="fts", limit=20)
    assert "projects/legacy-migration" in {hit.permalink for hit in results.hits}
    status = index.status()
    assert status.unresolved_relations > 0


async def test_reindex_of_unchanged_vault_is_a_no_op(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    before = index.status()
    reindexed = await index.reindex()
    after = index.status()
    assert reindexed == before.notes
    assert (after.notes, after.observations, after.relations) == (
        before.notes,
        before.observations,
        before.relations,
    )


async def test_reindex_drops_notes_that_vanished_from_disk(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(golden_work_vault)
    before = index.status().notes
    (golden_work_vault / "projects" / "curator.md").unlink()
    assert await index.reindex() == before - 1
    results = await index.search("curator", mode="fts", limit=20)
    assert "projects/curator" not in {hit.permalink for hit in results.hits}


async def test_doctor_verify_sees_no_index_drift_after_build(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    findings = await index.verify()
    codes = {finding.code for finding in findings}
    assert not codes & {"index-orphan-entry", "index-stale-entry", "index-missing-entry"}
    # And the doctor reached the index at all (it was handed an IndexView).
    assert list(index.index_entries())


async def test_doctor_verify_reports_stale_and_missing_index_entries(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    (golden_work_vault / "projects" / "curator.md").write_text(
        "---\ntitle: Curator\npermalink: projects/curator\ntype: project\n---\n\nedited\n",
        encoding="utf-8",
    )
    (golden_work_vault / "notes").mkdir(exist_ok=True)
    (golden_work_vault / "notes" / "brand-new.md").write_text(
        "---\ntitle: Brand New\npermalink: notes/brand-new\ntype: note\n---\n\nnew\n",
        encoding="utf-8",
    )
    engine.refresh_now()
    findings = await VaultDoctor(engine).verify(index)
    codes = {finding.code for finding in findings}
    assert "index-stale-entry" in codes
    assert "index-missing-entry" in codes
    # ... and reindexing clears both, because files are the only truth.
    await index.reindex()
    codes_after = {finding.code for finding in await index.verify()}
    assert not codes_after & {"index-stale-entry", "index-missing-entry"}


async def test_rebuild_after_filter_query_keeps_filters_working(
    golden_work_vault: Path, open_index: Any, tmp_path: Path
) -> None:
    db_path = tmp_path / "filters.sqlite3"
    engine, index = await open_index(golden_work_vault, index_path=db_path)
    query = "vault"
    filters = SearchFilters(types=("decision",), tags=("adr",))
    before = [hit.ref for hit in (await index.search(query, mode="fts", filters=filters)).hits]
    assert before
    await index.close()
    db_path.unlink()

    rebuilt = VaultIndex(engine, path=db_path)
    await rebuilt.open(start_worker=False)
    try:
        after = [
            hit.ref for hit in (await rebuilt.search(query, mode="fts", filters=filters)).hits
        ]
        assert after == before
    finally:
        await rebuilt.close()
