"""Chunking, the embed backlog, and clean degradation while it drains.

Uses the deterministic :class:`~stub_embedder.StubEmbedder`: the point here is
the *mechanism* — write ack never waits on an embed, status reports the
backlog, queries degrade to FTS while vectors are pending, and unchanged
chunks keep their vectors. Semantic quality is measured against the real model
in ``test_hybrid_relevance.py``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from stub_embedder import StubEmbedder

from palaia_hub.index import (
    EmbedderUnavailableError,
    EmbeddingConfig,
    VaultIndex,
    chunk_text,
    embeddable_text,
    fingerprint,
)
from palaia_hub.index import service as index_service
from palaia_hub.vault import EventBus, VaultEngine

pytestmark = pytest.mark.anyio


def _stub_config(**kwargs: Any) -> EmbeddingConfig:
    return EmbeddingConfig(enabled=True, model="stub/hashed-bow", **kwargs)


# ------------------------------------------------------------------- chunking


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_text("a short note body")
    assert len(chunks) == 1
    assert chunks[0].seq == 0
    assert chunks[0].fingerprint == fingerprint("a short note body")


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == []


def test_long_text_splits_on_paragraph_boundaries() -> None:
    paragraph = "sentence about vaults. " * 12  # ~276 chars
    text = "\n\n".join(paragraph for _ in range(10))
    chunks = chunk_text(text, max_chars=600, overlap_chars=60)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 600 for chunk in chunks)
    assert [chunk.seq for chunk in chunks] == list(range(len(chunks)))


def test_oversized_single_paragraph_is_hard_split_with_overlap() -> None:
    text = "x" * 2500
    chunks = chunk_text(text, max_chars=1000, overlap_chars=100)
    assert len(chunks) >= 3
    assert all(len(chunk.text) <= 1000 for chunk in chunks)


def test_fingerprints_are_stable_and_content_addressed() -> None:
    first = chunk_text("stable text")[0]
    second = chunk_text("stable text")[0]
    assert first.fingerprint == second.fingerprint
    assert chunk_text("other text")[0].fingerprint != first.fingerprint


def test_embeddable_text_includes_title_body_and_observations() -> None:
    text = embeddable_text("Title", "Body prose.", ["an observed fact"])
    assert text.splitlines()[0] == "Title"
    assert "Body prose." in text
    assert "an observed fact" in text


# ------------------------------------------------------------------- backlog


async def test_build_leaves_chunks_pending_and_status_reports_the_backlog(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    status = index.status()
    assert status.embeds.enabled
    assert status.embeds.pending == status.embeds.total > 0
    assert status.embeds.ready == 0


async def test_hybrid_degrades_to_fts_while_vectors_are_pending(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    results = await index.search("API Gateway", mode="hybrid", limit=5)
    assert results.mode == "hybrid"
    assert results.effective_mode == "fts"
    assert results.degraded
    assert "pending" in results.degraded_reason
    assert "projects/api-gateway" in {hit.permalink for hit in results.hits}


async def test_vector_mode_also_degrades_rather_than_returning_nothing(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    results = await index.search("API Gateway", mode="vector", limit=5)
    assert results.effective_mode == "fts"
    assert results.degraded
    assert results.hits


async def test_draining_the_backlog_enables_vector_and_hybrid_modes(
    golden_work_vault: Path, open_index: Any
) -> None:
    embedder = StubEmbedder()
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(batch_size=16), embedder=embedder
    )
    pending = index.status().embeds.pending
    embedded = await index.drain_embeddings()
    assert embedded == pending
    status = index.status()
    assert status.embeds.pending == 0
    assert status.embeds.ready == pending
    assert status.embeds.usable
    assert embedder.calls >= pending / 16

    vector = await index.search("gateway tool families per profile", mode="vector", limit=5)
    assert not vector.degraded
    assert vector.effective_mode == "vector"
    assert vector.hits

    hybrid = await index.search("API Gateway", mode="hybrid", limit=5)
    assert hybrid.effective_mode == "hybrid"
    assert not hybrid.degraded
    assert "projects/api-gateway" in {hit.permalink for hit in hybrid.hits}


async def test_background_worker_drains_the_backlog_without_being_asked(
    golden_work_vault: Path, open_index: Any
) -> None:
    """The write path never embeds; the worker does, on its own."""
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    assert index.status().embeds.pending > 0
    index.start_worker()
    deadline = asyncio.get_event_loop().time() + 10.0
    while asyncio.get_event_loop().time() < deadline:
        if index.status().embeds.pending == 0:
            break
        await asyncio.sleep(0.05)
    status = index.status()
    assert status.embeds.pending == 0
    assert status.embeds.ready > 0


async def test_worker_warms_embedder_for_a_ready_index_after_restart(
    golden_work_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted vector index loads its model in the worker, not a query."""
    db_path = tmp_path / "index.sqlite3"
    engine = VaultEngine(golden_work_vault, "work", bus=EventBus())
    await engine.open(purpose="embedder warmup test", create=True)
    first = VaultIndex(
        engine,
        path=db_path,
        embedding=_stub_config(batch_size=16),
        embedder=StubEmbedder(),
    )
    await first.open(start_worker=False)
    try:
        await first.drain_embeddings()
        assert first.status().embeds.pending == 0
        assert first.status().embeds.ready > 0
    finally:
        await first.close()

    warmed = StubEmbedder()
    builds = 0

    def build(_config: EmbeddingConfig) -> StubEmbedder:
        nonlocal builds
        builds += 1
        return warmed

    monkeypatch.setattr(index_service, "build_embedder", build)
    reopened = VaultIndex(engine, path=db_path, embedding=_stub_config(batch_size=16))
    await reopened.open(build=False)
    try:
        reopened.start_worker()
        deadline = asyncio.get_running_loop().time() + 1.0
        while builds == 0 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert builds == 1
    finally:
        await reopened.close()
        await engine.close()


async def test_failed_embedder_probe_retries_after_backoff(
    golden_work_vault: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient model-load failure must not disable vectors permanently."""
    attempts = 0
    recovered = StubEmbedder()

    def build(_config: EmbeddingConfig) -> StubEmbedder:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise EmbedderUnavailableError("temporary model download failure")
        return recovered

    monkeypatch.setattr(index_service, "build_embedder", build)
    _, index = await open_index(golden_work_vault, embedding=_stub_config())

    assert await index.embed_next_batch() == 0
    assert attempts == 1
    assert await index.embed_next_batch() == 0
    assert attempts == 1

    # Advance past the production backoff without making the test sleep.
    index._embedder_retry_at = 0.0
    assert await index.embed_next_batch() > 0
    assert attempts == 2
    assert index.status().embeds.reason == ""


async def test_editing_a_note_only_re_embeds_its_changed_chunks(
    golden_work_vault: Path, open_index: Any
) -> None:
    embedder = StubEmbedder()
    engine, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=embedder
    )
    long_body = "\n\n".join(f"Paragraph {n} about the vault engine. " * 20 for n in range(6))
    await engine.write_note(
        "notes/long.md", body=long_body + "\n", title="Long", frontmatter={"type": "note"}
    )
    await index.drain_embeddings()
    chunks_before = _chunk_rows(index, "notes/long")
    assert len(chunks_before) > 2

    current = await engine.read_note("notes/long")
    await engine.edit_note(
        "notes/long",
        body=long_body + "\n\nOne appended paragraph at the very end.\n",
        expected_checksum=current.checksum,
    )
    pending = [row for row in _chunk_rows(index, "notes/long") if row["state"] == "pending"]
    ready = [row for row in _chunk_rows(index, "notes/long") if row["state"] == "ready"]
    assert pending, "the changed tail must be re-embedded"
    assert ready, "unchanged chunks must keep their vectors"
    assert len(pending) < len(chunks_before)


async def test_reindex_preserves_ready_vectors(
    golden_work_vault: Path, open_index: Any
) -> None:
    embedder = StubEmbedder()
    _, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=embedder
    )
    await index.drain_embeddings()
    ready_before = index.status().embeds.ready
    calls_before = embedder.calls
    await index.reindex()
    assert index.status().embeds.ready == ready_before
    assert await index.drain_embeddings() == 0
    assert embedder.calls == calls_before


async def test_deleting_a_note_removes_its_chunks(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    await index.drain_embeddings()
    before = index.status().embeds.total
    removed = len(_chunk_rows(index, "projects/curator"))
    assert removed > 0
    await engine.delete_note("projects/curator")
    assert index.status().embeds.total == before - removed


async def test_disabled_embeddings_report_why_and_still_search(
    golden_work_vault: Path, open_index: Any
) -> None:
    _, index = await open_index(
        golden_work_vault, embedding=EmbeddingConfig(enabled=False)
    )
    status = index.status()
    assert not status.embeds.enabled
    results = await index.search("API Gateway", mode="hybrid", limit=5)
    assert results.degraded
    assert "disabled" in results.degraded_reason
    assert results.hits


async def test_unavailable_embedder_degrades_without_raising(
    golden_work_vault: Path, open_index: Any
) -> None:
    """A missing/broken model is an FTS-only index, not a broken hub."""
    _, index = await open_index(
        golden_work_vault,
        embedding=EmbeddingConfig(enabled=True, model="does-not-exist/nope"),
    )
    assert await index.embed_next_batch() == 0
    status = index.status()
    assert status.embeds.pending > 0
    assert not status.embeds.available
    assert status.embeds.reason
    results = await index.search("API Gateway", mode="hybrid", limit=5)
    assert results.effective_mode == "fts"
    assert results.hits


def _chunk_rows(index: Any, permalink: str) -> list[Any]:
    with index.db.lock:
        return index.db.conn.execute(
            "SELECT c.id, c.seq, c.state, c.fingerprint FROM chunks c "
            "JOIN notes n ON n.id = c.note_id WHERE n.permalink = ? ORDER BY c.seq",
            (permalink,),
        ).fetchall()
