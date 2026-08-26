"""The gateway's ``search`` tool, served by the index instead of a linear scan.

SPEC-104 wires :class:`~palaia_hub.gateway.wiring.EngineVaultService` to the
index — the spot that adapter's docstring marked. The tool contract itself does
not change (SPEC-113 snapshots it), so these tests assert the *contract* holds
while the results get better.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from palaia_hub.gateway.wiring import EngineVaultService

pytestmark = pytest.mark.anyio


async def test_indexed_search_returns_ranked_hits(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    hits = await service.search("API Gateway", limit=5)
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
    hits = await service.search("vault", limit=50)
    assert hits
    assert "meta/vault" not in {hit.permalink for hit in hits}


async def test_indexed_search_reports_one_result_per_note(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    hits = await service.search("how-to-apply", limit=20)
    permalinks = [hit.permalink for hit in hits]
    assert len(permalinks) == len(set(permalinks))


async def test_indexed_search_has_no_results_for_an_absent_term(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    assert await service.search("xyzzy-nonexistent-term-42") == []


async def test_search_without_an_index_still_scans(
    golden_work_vault: Path, open_index: Any
) -> None:
    """The SPEC-105 fallback stays: no index passed, no SQLite needed."""
    engine, _ = await open_index(golden_work_vault, build=False)
    service = EngineVaultService(engine)
    hits = await service.search("gateway", limit=5)
    assert any(hit.permalink == "projects/api-gateway" for hit in hits)


async def test_new_writes_are_searchable_through_the_tool_immediately(
    golden_work_vault: Path, open_index: Any
) -> None:
    engine, index = await open_index(golden_work_vault)
    service = EngineVaultService(engine, index)
    record = await service.write("Tool Written Note", "a body with lycanthropy in it")
    hits = await service.search("lycanthropy", limit=5)
    assert [hit.permalink for hit in hits] == [record.permalink]
