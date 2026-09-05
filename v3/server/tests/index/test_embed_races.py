"""Issue #336: the embed worker checks that a chunk is still the one it embedded.

Embedding takes seconds and runs off the lock. Before the fix the worker
stored its vector and marked the chunk ``ready`` by id alone — so a chunk
whose text had changed in the meantime (same id, new fingerprint, reset to
``pending`` by the writer) ended up ``ready`` with the *old* text's vector,
and a chunk deleted in the meantime got a vector row with no chunk behind it,
occupying KNN slots forever.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from stub_embedder import StubEmbedder

from palaia_hub.index import EmbeddingConfig, fingerprint
from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio


class RacingEmbedder(StubEmbedder):
    """A stub that lets the test act *while* a batch is being embedded."""

    def __init__(self) -> None:
        super().__init__()
        self.during_embed: Callable[[], None] | None = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        hook, self.during_embed = self.during_embed, None
        if hook is not None:
            hook()
        return super().embed(texts)


def _config() -> EmbeddingConfig:
    return EmbeddingConfig(enabled=True, model="stub/hashed-bow", batch_size=8)


def _chunk(index: Any, path: str) -> Any:
    with index.db.lock:
        return index.db.conn.execute(
            "SELECT c.id, c.state, c.fingerprint, c.text FROM chunks c "
            "JOIN notes n ON n.id = c.note_id WHERE n.path = ?",
            (path,),
        ).fetchone()


def _vector_count(index: Any, chunk_id: int | None = None) -> int:
    with index.db.lock:
        if chunk_id is None:
            row = index.db.conn.execute("SELECT COUNT(*) AS n FROM vec_chunks").fetchone()
        else:
            row = index.db.conn.execute(
                "SELECT COUNT(*) AS n FROM vec_chunks WHERE rowid = ?", (chunk_id,)
            ).fetchone()
    return int(row["n"])


async def _quiet_vault(
    tmp_path: Path, open_index: Any, embedder: RacingEmbedder
) -> tuple[Any, Any]:
    """An opened vault with nothing pending, so the next batch is ours."""
    engine, index = await open_index(tmp_path / "race", embedding=_config(), embedder=embedder)
    if not index.db.vectors.available:
        pytest.skip(index.db.vectors.reason)
    await index.drain_embeddings()
    assert index.status().embeds.pending == 0
    return engine, index


def _rewrite_on_disk(engine: VaultEngine, path: str, text: str) -> None:
    (engine.root / path).write_text(text, encoding="utf-8")


async def test_a_chunk_edited_while_embedding_stays_pending_with_no_stale_vector(
    tmp_path: Path, open_index: Any
) -> None:
    embedder = RacingEmbedder()
    engine, index = await _quiet_vault(tmp_path, open_index, embedder)
    await engine.write_note("notes/race", body="The original paragraph.\n", title="Race")
    claimed = _chunk(index, "notes/race.md")
    assert claimed["state"] == "pending"

    def edit_underneath() -> None:
        # The writer, reacting to an edit that landed mid-embed: same chunk
        # id, new text and fingerprint, back to pending.
        _rewrite_on_disk(
            engine,
            "notes/race.md",
            "---\ntitle: Race\npermalink: notes/race\n---\n\nA completely different paragraph.\n",
        )
        index.writer.upsert_note(engine.read_note_at("notes/race.md"))

    embedder.during_embed = edit_underneath
    stored = await index.embed_next_batch()

    assert stored == 0
    after = _chunk(index, "notes/race.md")
    assert after["id"] == claimed["id"]
    assert after["state"] == "pending", "the stale vector must not mark the new text ready"
    assert after["fingerprint"] != claimed["fingerprint"]
    assert _vector_count(index, int(after["id"])) == 0

    # The next batch embeds the *new* text and only then marks it ready.
    assert await index.embed_next_batch() == 1
    final = _chunk(index, "notes/race.md")
    assert final["state"] == "ready"
    assert "completely different" in embedder.embedded[-1]
    assert _vector_count(index, int(final["id"])) == 1


async def test_a_chunk_deleted_while_embedding_leaves_no_orphan_vector(
    tmp_path: Path, open_index: Any
) -> None:
    embedder = RacingEmbedder()
    engine, index = await _quiet_vault(tmp_path, open_index, embedder)
    vectors_before = _vector_count(index)
    await engine.write_note("notes/gone", body="Will be deleted mid-embed.\n", title="Gone")
    claimed = _chunk(index, "notes/gone.md")

    embedder.during_embed = lambda: index.writer.delete_note("notes/gone.md")
    stored = await index.embed_next_batch()

    assert stored == 0
    assert _chunk(index, "notes/gone.md") is None
    assert _vector_count(index, int(claimed["id"])) == 0
    assert _vector_count(index) == vectors_before


async def test_a_failed_batch_does_not_count_against_a_chunk_that_changed(
    tmp_path: Path, open_index: Any
) -> None:
    """The attempt counter parks a chunk as ``failed`` after three strikes;
    strikes earned by text that no longer exists must not carry over."""
    embedder = RacingEmbedder()
    engine, index = await _quiet_vault(tmp_path, open_index, embedder)
    await engine.write_note("notes/flaky", body="First text.\n", title="Flaky")

    def change_then_fail() -> None:
        _rewrite_on_disk(
            engine,
            "notes/flaky.md",
            "---\ntitle: Flaky\npermalink: notes/flaky\n---\n\nSecond text.\n",
        )
        index.writer.upsert_note(engine.read_note_at("notes/flaky.md"))
        raise RuntimeError("backend blip")

    embedder.during_embed = change_then_fail
    assert await index.embed_next_batch() == 0

    with index.db.lock:
        row = index.db.conn.execute(
            "SELECT attempts, state FROM chunks c JOIN notes n ON n.id = c.note_id "
            "WHERE n.path = ?",
            ("notes/flaky.md",),
        ).fetchone()
    assert (int(row["attempts"]), str(row["state"])) == (0, "pending")


async def test_the_rebuild_sweeps_orphan_vectors(tmp_path: Path, open_index: Any) -> None:
    """Belt and braces: anything that slipped through is removed by the next
    rebuild, so orphans can never accumulate."""
    import sqlite_vec

    embedder = RacingEmbedder()
    _, index = await _quiet_vault(tmp_path, open_index, embedder)
    orphan_id = 987654
    with index.db.lock:
        index.db.conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (orphan_id, sqlite_vec.serialize_float32([1.0] + [0.0] * (embedder.dim - 1))),
        )
        index.db.conn.commit()
    assert _vector_count(index, orphan_id) == 1

    await index.reindex()

    assert _vector_count(index, orphan_id) == 0
    # Real vectors survive the sweep.
    assert _vector_count(index) == index.status().embeds.ready


def test_fingerprint_is_what_the_claim_carries() -> None:
    """The guard compares the chunk's stored fingerprint with the one the
    text was claimed under — both come from the same function."""
    assert fingerprint("a") == fingerprint("a")
    assert fingerprint("a") != fingerprint("b")
