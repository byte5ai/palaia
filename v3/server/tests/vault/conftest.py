"""Fixtures for the vault-engine tests. Plain helpers live in vault_helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from vault_helpers import TEST_POLICY, EngineFactory

from palaia_hub.vault import EventBus, GitPolicy, VaultEngine


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio-marked tests on asyncio only."""
    return "asyncio"


@pytest.fixture
def make_engine(tmp_path: Path) -> EngineFactory:
    """Return a factory that creates and opens isolated vaults."""

    async def factory(
        name: str = "work",
        *,
        bus: EventBus | None = None,
        policy: GitPolicy = TEST_POLICY,
        root: Path | None = None,
        **kwargs: object,
    ) -> VaultEngine:
        vault_root = root if root is not None else tmp_path / name
        engine = VaultEngine(vault_root, name, bus=bus, policy=policy, **kwargs)  # type: ignore[arg-type]
        await engine.open(purpose=f"test vault {name}")
        return engine

    return factory
