"""Shared fixtures for the vault-engine tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from palaia_hub.vault import Attribution, EventBus, GitPolicy, VaultEngine

#: Git policy for tests: repack early, never in the background (deterministic
#: sizes), and treat locks as stale quickly so crash recovery is testable
#: without sleeping for the production threshold.
TEST_POLICY = GitPolicy(
    gc_auto=64,
    gc_auto_pack_limit=4,
    gc_detach=False,
    gc_commit_interval=64,
    stale_lock_after=0.25,
)

TEST_ATTRIBUTION = Attribution(
    agent="curator",
    client="claude-code",
    provider="anthropic",
    session="s-42",
)


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio-marked tests on asyncio only."""
    return "asyncio"


EngineFactory = Callable[..., Awaitable[VaultEngine]]


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


def write_raw(engine: VaultEngine, relative: str, text: str) -> Path:
    """Write a file straight to disk, bypassing the engine (external editor)."""
    path = engine.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
