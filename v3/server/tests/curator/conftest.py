"""Fixtures for the curator suite (SPEC-206)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.vault import VaultEngine


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def vault_mount() -> VaultMountConfig:
    return VaultMountConfig(
        key="work", name="work", purpose="Team knowledge for ACME engineering."
    )


@pytest.fixture
def vault_root(tmp_path: Path) -> Iterator[Path]:
    root = tmp_path / "work"
    root.mkdir()
    yield root


@pytest.fixture
async def engine(vault_root: Path) -> AsyncIterator[VaultEngine]:
    engine = VaultEngine(vault_root, name="work")
    await engine.open(purpose="Team knowledge for ACME engineering.", create=True)
    try:
        yield engine
    finally:
        await engine.close()
