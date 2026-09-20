"""Fixtures for the hub-doctor tests (issue #296)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from palaia_hub.config import HubConfig
from palaia_hub.doctor import DoctorContext
from palaia_hub.vault import EventBus
from palaia_hub.vault.engine import VaultEngine

VaultFactory = Callable[..., Awaitable[VaultEngine]]


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio-marked tests on asyncio only."""
    return "asyncio"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """An empty hub home directory."""
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def context(home: Path) -> DoctorContext:
    """The smallest honest context: default config, nothing else opened."""
    return DoctorContext(config=HubConfig(), home=home)


@pytest.fixture
def make_vault(tmp_path: Path) -> VaultFactory:
    """Create and open an isolated vault, the way the hub would."""

    async def factory(name: str = "work") -> VaultEngine:
        engine = VaultEngine(tmp_path / "vaults" / name, name, bus=EventBus())
        await engine.open(purpose=f"doctor test vault {name}")
        return engine

    return factory
