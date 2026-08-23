"""Plain helpers for the SPEC-106 suite (fixtures live in ``conftest``).

Same split as the vault suite's ``vault_helpers``: anything a test wants to
call directly — rather than receive as a fixture — lives here, so it can be
imported without pytest's fixture machinery in the way.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import VaultEngine

GOLDEN_VAULT_ROOT = Path(__file__).parent.parent / "fixtures" / "golden-vault"

#: The instant every clock-reading assertion in this suite runs at. Fixed so
#: recency-sensitive expectations do not drift as months pass.
FROZEN_NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)


def frozen_clock(now: datetime = FROZEN_NOW) -> Callable[[], datetime]:
    """A clock that always returns ``now``."""
    return lambda: now


async def open_vault(root: Path, name: str = "work") -> tuple[VaultEngine, VaultIndex]:
    """Open an engine + index pair over ``root``, embeddings off.

    Embeddings are disabled on purpose: a hybrid query with no vectors
    degrades to FTS (SPEC-104's own acceptance criterion), which is
    deterministic, needs no model download, and is what CI runs anyway.
    """
    engine = VaultEngine(root, name)
    await engine.open(purpose=f"SPEC-106 test vault {name!r}", create=True)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open()
    return engine, index


async def open_golden(tmp_path: Path, name: str = "work") -> tuple[VaultEngine, VaultIndex]:
    """Copy one golden vault into ``tmp_path`` and open engine + index over it."""
    root = tmp_path / name
    shutil.copytree(GOLDEN_VAULT_ROOT / name, root)
    return await open_vault(root, name)


__all__ = [
    "FROZEN_NOW",
    "GOLDEN_VAULT_ROOT",
    "frozen_clock",
    "open_golden",
    "open_vault",
]
