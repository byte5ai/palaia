"""SPEC-210 deliverable #2: the import path drains through the real
SPEC-104 embed backlog, with progress visible via
:meth:`~palaia_hub.index.VaultIndex.status` and a done-event fired once the
backlog empties.

Every note :class:`~palaia_hub.importers.runner.ImportRunner` writes goes
through :meth:`~palaia_hub.vault.engine.VaultEngine.write_note`, which
publishes a change event on the engine's bus; a
:class:`~palaia_hub.index.VaultIndex` subscribed to that same bus (as
production wiring — :mod:`palaia_hub.serve` — always opens one for every
vault it serves) picks the note up automatically. No importer-specific
plumbing is needed beyond that subscription existing at all — this test is
the proof.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from palaia_hub.importers.models import MappedNote
from palaia_hub.importers.runner import ImportRunner
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import EventBus, VaultEngine

pytestmark = pytest.mark.anyio

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _StubEmbedder:
    """Deterministic hashed-bag-of-words embedder — no model download."""

    dim = 64
    name = "stub/hashed-bow"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[digest[0] % self.dim] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]


def _notes(count: int) -> list[MappedNote]:
    return [
        MappedNote(
            source_path=f"source/{i:03d}.md",
            permalink=f"imported/note-{i:03d}",
            title=f"Imported Note {i:03d}",
            body=f"Body text for imported note number {i:03d}, about topic {i % 5}.",
            frontmatter={},
            describe=f"note {i:03d}",
        )
        for i in range(count)
    ]


async def test_fifty_note_import_is_fts_searchable_immediately_and_embeds_drain(
    tmp_path: Path,
) -> None:
    engine = VaultEngine(tmp_path / "vault", "work", bus=EventBus())
    await engine.open(create=True)

    drained_events: list[object] = []
    index = VaultIndex(
        engine,
        embedding=EmbeddingConfig(enabled=True),
        embedder=_StubEmbedder(),  # type: ignore[arg-type]
        on_backlog_drained=drained_events.append,
    )
    await index.open(start_worker=False)  # drain manually below, deterministically

    runner = ImportRunner(engine)
    report = await runner.run("v2", str(tmp_path), _notes(50), dry_run=False)
    assert report.created_count == 50

    # Searchable immediately: FTS never waits on the embed backlog.
    fts_result = await index.search("Imported Note 007", mode="fts")
    assert any("note-007" in hit.ref for hit in fts_result.hits)

    status_before = index.status()
    assert status_before.counts_by_type["note"] == 50
    pending_before = status_before.embeds.pending
    assert pending_before >= 50
    assert status_before.embeds.ready == 0

    drained = await index.drain_embeddings()
    assert drained == pending_before

    status_after = index.status()
    assert status_after.embeds.pending == 0
    assert status_after.embeds.ready == pending_before

    # Hybrid search now has vectors to fuse with FTS.
    hybrid_result = await index.search("topic 3", mode="hybrid")
    assert not hybrid_result.degraded

    await index.close()
    await engine.close()


async def test_backlog_drained_callback_fires_once_the_worker_empties_it(
    tmp_path: Path,
) -> None:
    engine = VaultEngine(tmp_path / "vault", "work", bus=EventBus())
    await engine.open(create=True)

    drained_events: list[object] = []
    index = VaultIndex(
        engine,
        embedding=EmbeddingConfig(enabled=True),
        embedder=_StubEmbedder(),  # type: ignore[arg-type]
        on_backlog_drained=drained_events.append,
    )
    await index.open(start_worker=True)  # the real background worker this time

    runner = ImportRunner(engine)
    await runner.run("v2", str(tmp_path), _notes(10), dry_run=False)

    for _ in range(200):
        if drained_events:
            break
        await asyncio.sleep(0.05)

    assert len(drained_events) >= 1
    assert drained_events[-1].embeds.pending == 0
    assert drained_events[-1].embeds.ready >= 10

    await index.close()
    await engine.close()
