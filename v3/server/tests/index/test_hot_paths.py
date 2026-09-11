"""Issue #404: the index layer's per-call hot paths.

Every ``memory://`` resolution looked observations/relations up by their
synthetic permalink without an index, every note write probed
``sqlite_master`` once per chunk, every hybrid query re-aggregated the
chunk states, and a plain file move re-chunked (and re-embedded) the note.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from stub_embedder import StubEmbedder

from palaia_hub.index import EmbeddingConfig

pytestmark = pytest.mark.anyio


def _index_names(index: Any, table: str) -> set[str]:
    with index.db.lock:
        rows = index.db.conn.execute(f"PRAGMA index_list('{table}')").fetchall()
    return {str(row["name"]) for row in rows}


async def test_synthetic_permalinks_are_indexed(golden_work_vault: Path, open_index: Any) -> None:
    _, index = await open_index(golden_work_vault)
    assert "observations_permalink" in _index_names(index, "observations")
    assert "relations_permalink" in _index_names(index, "relations")


async def test_an_existing_database_gains_the_indexes_on_open(
    golden_work_vault: Path, open_index: Any, tmp_path: Path
) -> None:
    """No schema-version bump (which would rebuild every hub's index): the
    indexes are added with IF NOT EXISTS whenever the file is opened."""
    db_path = tmp_path / "index.sqlite3"
    _, index = await open_index(golden_work_vault, index_path=db_path)
    with index.db.lock:
        index.db.conn.execute("DROP INDEX observations_permalink")
        index.db.conn.execute("DROP INDEX relations_permalink")
        index.db.conn.commit()
    assert "observations_permalink" not in _index_names(index, "observations")
    await index.close()

    _, reopened = await open_index(golden_work_vault, name="work2", index_path=db_path, build=False)
    assert "observations_permalink" in _index_names(reopened, "observations")
    assert "relations_permalink" in _index_names(reopened, "relations")


async def test_the_vec_table_probe_is_answered_from_memory_after_the_first_call(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(
        golden_work_vault, embedding=EmbeddingConfig(enabled=True), embedder=StubEmbedder()
    )
    index.db._vec_table_known = None
    first = index.db.has_vec_table()
    assert index.db._vec_table_known is first
    if index.db.vectors.available:
        assert index.db.ensure_vec_table(64) is True
        assert index.db.has_vec_table() is True
        assert index.db._vec_table_known is True


async def test_embed_counts_are_recomputed_only_after_a_commit(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault, embedding=EmbeddingConfig(enabled=True))
    first = index.embed_status()
    cached = index._embed_counts
    assert cached is not None and cached[0] == index.db.generation
    assert index.embed_status().pending == first.pending
    assert index._embed_counts is cached, "no commit happened, so no re-aggregation"

    await engine.write_note("notes/new.md", body="Fresh text for a new chunk.\n", title="New")
    assert index.db.generation > cached[0]
    assert index.embed_status().pending > first.pending


async def test_a_pure_move_keeps_the_notes_ready_vectors(
    golden_work_vault: Path, open_index: Any
) -> None:
    embedder = StubEmbedder()
    engine, index = await open_index(
        golden_work_vault, embedding=EmbeddingConfig(enabled=True), embedder=embedder
    )
    if not index.db.vectors.available:
        pytest.skip("sqlite-vec not available")
    await index.drain_embeddings()
    assert index.status().embeds.pending == 0
    calls_before = embedder.calls

    with index.db.lock:
        row = index.db.conn.execute(
            "SELECT id, permalink FROM notes WHERE path = 'projects/vault-engine.md'"
        ).fetchone()
        chunk_ids_before = [
            int(r["id"])
            for r in index.db.conn.execute(
                "SELECT id FROM chunks WHERE note_id = ? ORDER BY id", (int(row["id"]),)
            ).fetchall()
        ]
    assert chunk_ids_before

    await engine.move_note("projects/vault-engine", "archive/vault-engine.md")

    with index.db.lock:
        moved = index.db.conn.execute(
            "SELECT id, permalink, folder FROM notes WHERE path = 'archive/vault-engine.md'"
        ).fetchone()
        gone = index.db.conn.execute(
            "SELECT 1 FROM notes WHERE path = 'projects/vault-engine.md'"
        ).fetchone()
        chunk_ids_after = [
            int(r["id"])
            for r in index.db.conn.execute(
                "SELECT id FROM chunks WHERE note_id = ? AND state = 'ready' ORDER BY id",
                (int(moved["id"]),),
            ).fetchall()
        ]
    assert gone is None
    assert int(moved["id"]) == int(row["id"])
    assert str(moved["permalink"]) == str(row["permalink"])
    assert str(moved["folder"]) == "archive"
    assert chunk_ids_after == chunk_ids_before, "the move must not re-chunk the note"
    assert index.status().embeds.pending == 0
    assert embedder.calls == calls_before, "nothing to re-embed after a pure move"
