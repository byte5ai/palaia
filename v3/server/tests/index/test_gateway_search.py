"""The gateway's ``search`` tool, served by the index instead of a linear scan.

SPEC-104 wires :class:`~palaia_hub.gateway.wiring.EngineVaultService` to the
index — the spot that adapter's docstring marked. The tool contract itself does
not change (SPEC-113 snapshots it), so these tests assert the *contract* holds
while the results get better.

Issue #294 adds the provenance half: the index has always known which channel
found a hit and whether the vector path degraded, and the adapter now passes
that through instead of dropping it at the boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from stub_embedder import StubEmbedder

from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig

pytestmark = pytest.mark.anyio


def _stub_config(**kwargs: Any) -> EmbeddingConfig:
    return EmbeddingConfig(enabled=True, model="stub/hashed-bow", **kwargs)


async def test_indexed_search_returns_ranked_hits(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    hits = (await service.search("API Gateway", limit=5)).hits
    assert hits
    assert hits[0].permalink == "projects/api-gateway"
    assert hits[0].title == "API Gateway"
    assert all(hit.score > 0 for hit in hits)
    assert len(hits) <= 5


async def test_indexed_search_excludes_meta_notes(
    golden_work_vault: Path, open_index: Any
) -> None:
    """Format spec §6: ``meta`` stays out of normal recall."""
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    hits = (await service.search("vault", limit=50)).hits
    assert hits
    assert "meta/vault" not in {hit.permalink for hit in hits}


async def test_indexed_search_reports_one_result_per_note(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    hits = (await service.search("how-to-apply", limit=20)).hits
    permalinks = [hit.permalink for hit in hits]
    assert len(permalinks) == len(set(permalinks))


async def test_indexed_search_has_no_results_for_an_absent_term(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    assert (await service.search("xyzzy-nonexistent-term-42")).hits == []


async def test_search_without_an_index_still_scans(
    golden_work_vault: Path, open_index: Any
) -> None:
    """The SPEC-105 fallback stays: no index passed, no SQLite needed."""
    engine, _ = await open_index(golden_work_vault, build=False)
    service = EngineVaultService(engine)
    hits = (await service.search("gateway", limit=5)).hits
    assert any(hit.permalink == "projects/api-gateway" for hit in hits)


async def test_new_writes_are_searchable_through_the_tool_immediately(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    record = await service.write("Tool Written Note", "a body with lycanthropy in it")
    hits = (await service.search("lycanthropy", limit=5)).hits
    assert [hit.permalink for hit in hits] == [record.permalink]


# ---------------------------------------------- issue #294: hit provenance


async def test_hybrid_search_reports_the_channel_and_rank_per_hit(
    golden_work_vault: Path, open_index: Any
) -> None:
    """With vectors ready, every hit names the channel(s) that found it."""
    engine, index = await open_index(
        golden_work_vault, embedding=_stub_config(), embedder=StubEmbedder()
    )
    await index.drain_embeddings()
    service = EngineVaultService(engine, index)

    response = await service.search("API Gateway", limit=5)
    assert response.mode == "hybrid"
    assert response.effective_mode == "hybrid"
    assert response.degraded is False
    assert response.degraded_reason == ""
    assert response.hits

    for hit in response.hits:
        assert hit.matched, f"{hit.permalink} reports no matching channel"
        assert set(hit.matched) <= {"text", "meaning"}
        # `matched` and the raw ranks must not disagree: a channel is
        # listed exactly when that channel produced a rank for the hit.
        assert ("text" in hit.matched) == (hit.fts_rank is not None)
        assert ("meaning" in hit.matched) == (hit.vector_rank is not None)
        assert all(rank >= 1 for rank in (hit.fts_rank, hit.vector_rank) if rank is not None)

    # The stub embedder is lexical, so this query is found by both channels —
    # which is the signal the fields exist to expose.
    assert any(set(hit.matched) == {"text", "meaning"} for hit in response.hits)


async def test_hybrid_without_vectors_reports_degraded_and_the_text_channel(
    golden_work_vault: Path, open_index: Any
) -> None:
    """SPEC-104's honesty signal, now visible at the tool boundary.

    Embeddings are off in this fixture, so the hybrid query runs as
    full-text only. The index's single-channel result sets carry no ranks,
    so every hit is attributed to the one channel that ran rather than to
    nothing at all.
    """
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)

    response = await service.search("API Gateway", limit=5)
    assert response.mode == "hybrid"
    assert response.effective_mode == "fts"
    assert response.degraded is True
    assert response.degraded_reason
    assert response.hits
    assert all(hit.matched == ["text"] for hit in response.hits)
