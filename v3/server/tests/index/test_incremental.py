"""Incremental updates from SPEC-102 change events.

The two behaviors this SPEC's model note calls out as "where the judgment
lives": incremental-update correctness, and forward-reference resolution
happening *without* a full reindex.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.vault import VaultWatcher

pytestmark = pytest.mark.anyio

#: SPEC-104 acceptance criterion: index lag after a change event < 2 s.
_LAG_BUDGET_SECONDS = 2.0


def _unresolved_targets(index: Any) -> set[str]:
    with index.db.lock:
        rows = index.db.conn.execute(
            "SELECT target_raw FROM relations WHERE target_permalink IS NULL"
        ).fetchall()
    return {str(row["target_raw"]) for row in rows}


def _relation_row(index: Any, target_raw: str) -> Any:
    with index.db.lock:
        return index.db.conn.execute(
            "SELECT permalink, target_permalink FROM relations WHERE target_raw = ?",
            (target_raw,),
        ).fetchone()


async def test_write_through_engine_updates_index_via_event(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    before = index.status().notes
    await engine.write_note(
        "notes/incremental.md",
        body="A note written through the engine, indexed by its event.\n",
        title="Incremental",
        frontmatter={"type": "note"},
    )
    assert index.status().notes == before + 1
    results = await index.search("indexed by its event", mode="fts", limit=5)
    assert [hit.permalink for hit in results.hits] == ["notes/incremental"]


async def test_edit_replaces_stale_text(golden_work_vault: Path, open_index: Any) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "notes/mutable.md",
        body="original haystack sentinel\n",
        title="Mutable",
        frontmatter={"type": "note"},
    )
    assert (await index.search("sentinel", mode="fts")).hits
    current = await engine.read_note("notes/mutable")
    await engine.edit_note(
        "notes/mutable", body="replaced entirely\n", expected_checksum=current.checksum
    )
    assert list(await index.search("sentinel", mode="fts")) == []
    assert (await index.search("replaced entirely", mode="fts")).hits


async def test_delete_removes_the_note_and_its_subrows(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    before = index.status()
    await engine.delete_note("rules/how-to-write-commit-messages")
    after = index.status()
    assert after.notes == before.notes - 1
    assert after.observations < before.observations
    assert list(await index.search("imperative phrasing", mode="fts")) == []


async def test_move_keeps_identity_and_updates_the_folder(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.move_note("projects/curator", "archive/curator.md")
    hits = (await index.search("curator", mode="fts", limit=20)).hits
    moved = [hit for hit in hits if hit.permalink == "projects/curator"]
    assert moved, "a move keeps the permalink (§3.1)"
    assert moved[0].path == "archive/curator.md"
    assert index.status().notes == len(list(golden_work_vault.rglob("*.md")))


async def test_forward_reference_resolves_when_target_appears_without_reindex(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "projects/waiting.md",
        body="Depends on something that does not exist yet.\n\n- depends_on [[Ghost Project]]\n",
        title="Waiting",
        frontmatter={"type": "project"},
    )
    assert "Ghost Project" in _unresolved_targets(index)
    unresolved_before = index.status().unresolved_relations

    # The target appears. No reindex is called anywhere in this test — only
    # the note-created event path runs.
    await engine.write_note(
        "projects/ghost-project.md",
        body="Here at last.\n",
        title="Ghost Project",
        frontmatter={"type": "project"},
    )

    assert "Ghost Project" not in _unresolved_targets(index)
    assert index.status().unresolved_relations == unresolved_before - 1
    row = _relation_row(index, "Ghost Project")
    assert row["target_permalink"] == "projects/ghost-project"
    # The synthetic relation permalink now addresses the resolved target (§9.2).
    assert str(row["permalink"]) == "projects/waiting/rel/depends-on/projects/ghost-project"
    refs = {
        hit.ref
        for hit in (await index.search("depends_on Ghost Project", mode="fts", limit=20)).hits
    }
    assert "projects/waiting/rel/depends-on/projects/ghost-project" in refs


async def test_forward_reference_resolves_through_an_alias(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    await engine.write_note(
        "projects/needs-alias.md",
        body="- depends_on [[Legacy Name]]\n",
        title="Needs Alias",
        frontmatter={"type": "project"},
    )
    assert "Legacy Name" in _unresolved_targets(index)
    await engine.write_note(
        "projects/current-name.md",
        body="Renamed long ago.\n",
        title="Current Name",
        frontmatter={"type": "project", "aliases": ["Legacy Name"]},
    )
    assert _relation_row(index, "Legacy Name")["target_permalink"] == "projects/current-name"


async def test_deleting_a_target_turns_relations_back_into_forward_references(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    assert _relation_row(index, "Vault Engine")["target_permalink"] == "projects/vault-engine"
    await engine.delete_note("projects/vault-engine")
    assert _relation_row(index, "Vault Engine")["target_permalink"] is None
    assert "Vault Engine" in _unresolved_targets(index)


async def test_rename_reindexes_and_keeps_backlinks_resolved(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    result = await engine.rename_entity("projects/vault-engine", "Vault Core")
    assert result.rewritten_links > 0
    # The rename rewrote inbound links vault-wide; every one of them still
    # points at a resolved target afterwards.
    with index.db.lock:
        stale = index.db.conn.execute(
            "SELECT COUNT(*) AS n FROM relations WHERE target_raw = 'Vault Engine'"
        ).fetchone()["n"]
    assert int(stale) == 0
    assert _relation_row(index, "Vault Core")["target_permalink"] == "projects/vault-core"
    hits = await index.search("Vault Core", mode="fts", limit=10)
    assert "projects/vault-core" in {hit.permalink for hit in hits.hits}


async def test_external_edit_is_indexed_within_the_lag_budget(
    golden_work_vault: Path, open_index: Any
) -> None:
    """A file written straight to disk becomes searchable in under 2 s."""
    engine, index = await open_index(golden_work_vault)
    watcher = VaultWatcher(engine)
    await watcher.start()
    try:
        # watchfiles has no "watch established" signal; settle briefly first.
        await _sleep(0.3)
        target = golden_work_vault / "notes" / "written-outside.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        target.write_text(
            "---\ntitle: Written Outside\npermalink: notes/written-outside\ntype: note\n---\n\n"
            "This body arrived from an external editor.\n",
            encoding="utf-8",
        )
        lag = None
        while time.monotonic() - started < 10.0:
            hits = await index.search("arrived from an external editor", mode="fts", limit=5)
            if any(hit.permalink == "notes/written-outside" for hit in hits.hits):
                lag = time.monotonic() - started
                break
            await _sleep(0.05)
        assert lag is not None, "external edit never reached the index"
        assert lag < _LAG_BUDGET_SECONDS, f"index lag {lag:.2f}s exceeds {_LAG_BUDGET_SECONDS}s"
    finally:
        await watcher.stop()


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
