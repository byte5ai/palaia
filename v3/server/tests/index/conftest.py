"""Fixtures for the SPEC-104 index tests.

The golden vault (SPEC-113 deliverable #1) is the corpus here too — its
acceptance criterion says any SPEC may import it — so the rebuild-identity
and relevance checks run against the same notes the e2e scenarios do, rather
than against a fixture invented for this SPEC alone.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import EventBus, VaultEngine

GOLDEN_VAULT_ROOT = Path(__file__).parent.parent / "fixtures" / "golden-vault"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def golden_work_vault(tmp_path: Path) -> Path:
    """A disposable copy of the golden vault's ``work`` vault."""
    target = tmp_path / "work"
    shutil.copytree(GOLDEN_VAULT_ROOT / "work", target)
    return target


IndexFactory = Callable[..., "AsyncIterator[tuple[VaultEngine, VaultIndex]]"]


@pytest.fixture
async def open_index() -> AsyncIterator[Callable[..., object]]:
    """Factory yielding opened ``(engine, index)`` pairs, closed on teardown.

    Embeddings default to *off*: the FTS/incremental/rebuild behavior is
    independent of them, and a unit test must not download a model. Tests that
    care about vectors pass their own ``embedder`` (a deterministic stub) or
    switch embeddings on explicitly.
    """
    opened: list[tuple[VaultEngine, VaultIndex]] = []

    async def factory(
        root: Path,
        name: str = "work",
        *,
        embedding: EmbeddingConfig | None = None,
        embedder: object | None = None,
        build: bool = True,
        index_path: Path | None = None,
    ) -> tuple[VaultEngine, VaultIndex]:
        engine = VaultEngine(root, name, bus=EventBus())
        await engine.open(purpose=f"index test vault {name}", create=True)
        index = VaultIndex(
            engine,
            path=index_path,
            embedding=embedding or EmbeddingConfig(enabled=False),
            embedder=embedder,  # type: ignore[arg-type]
        )
        await index.open(build=build, start_worker=False)
        opened.append((engine, index))
        return engine, index

    yield factory

    for engine, index in reversed(opened):
        await index.close()
        await engine.close()
