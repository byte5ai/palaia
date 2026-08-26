"""Fixtures for the SPEC-106 recall suite. Plain helpers live in recall_helpers.

Two things are deliberately fixed across the whole suite so ranking
assertions stay honest: **embeddings off** (deterministic FTS-only retrieval,
no model download — see :func:`recall_helpers.open_vault`) and **a frozen
clock** (decay scoring reads one, and a test reading the real clock would
drift its own expectations over months).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from recall_helpers import frozen_clock, open_golden

from palaia_hub.index import VaultIndex
from palaia_hub.recall import RecallService
from palaia_hub.vault import VaultEngine


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def golden_work(tmp_path: Path) -> AsyncIterator[tuple[VaultEngine, VaultIndex]]:
    """A disposable copy of the golden ``work`` vault, engine + index open."""
    engine, index = await open_golden(tmp_path, "work")
    try:
        yield engine, index
    finally:
        await index.close()
        await engine.close()


@pytest.fixture
async def golden_recall(golden_work: tuple[VaultEngine, VaultIndex]) -> RecallService:
    """A :class:`RecallService` over the golden vault: frozen clock, no counters.

    ``track_access=False`` because a battery of queries in one test would
    otherwise have each query's access bump influence the next query's
    ranking — the assertions would then depend on test *order*, which is
    exactly the coupling a ranking regression suite must not have. The
    counters get their own dedicated tests.
    """
    engine, index = golden_work
    return RecallService(index, vault=engine.name, track_access=False, clock=frozen_clock())
