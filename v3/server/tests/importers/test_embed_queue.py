"""Unit tests for the cold-embed queue seam (SPEC-111 deliverable #3)."""

from __future__ import annotations

from pathlib import Path

from palaia_hub.importers.embed_queue import enqueue_for_embedding, queue_status


def test_empty_queue_reports_zero(tmp_path: Path) -> None:
    status = queue_status(tmp_path / ".palaia")
    assert status.pending == 0
    assert status.embedded == 0
    assert status.oldest_pending_permalink is None


def test_enqueue_is_visible_and_ordered_oldest_first(tmp_path: Path) -> None:
    engine_dir = tmp_path / ".palaia"
    enqueue_for_embedding(engine_dir, permalink="notes/b", enqueued_at="2026-01-02T00:00:00Z")
    enqueue_for_embedding(engine_dir, permalink="notes/a", enqueued_at="2026-01-01T00:00:00Z")

    status = queue_status(engine_dir)
    assert status.pending == 2
    assert status.embedded == 0
    assert status.oldest_pending_permalink == "notes/a"
    assert status.oldest_pending_enqueued_at == "2026-01-01T00:00:00Z"


def test_malformed_lines_are_tolerated(tmp_path: Path) -> None:
    engine_dir = tmp_path / ".palaia"
    engine_dir.mkdir(parents=True)
    (engine_dir / "import-embed-queue.jsonl").write_text(
        "not json\n{\"permalink\": \"notes/x\", \"enqueued_at\": \"2026-01-01T00:00:00Z\"}\n",
        encoding="utf-8",
    )
    status = queue_status(engine_dir)
    assert status.pending == 1
    assert status.oldest_pending_permalink == "notes/x"
