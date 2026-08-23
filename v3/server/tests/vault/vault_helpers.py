"""Shared constants and helpers for the vault-engine tests.

Kept out of ``conftest.py`` on purpose: these are imported by name, and a
module called ``conftest`` is ambiguous as soon as another test directory adds
one. Fixtures live in ``conftest.py``; plain values and functions live here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from palaia_hub.vault import Attribution, GitPolicy, VaultEngine

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

EngineFactory = Callable[..., Awaitable[VaultEngine]]


def write_raw(engine: VaultEngine, relative: str, text: str) -> Path:
    """Write a file straight to disk, bypassing the engine (external editor)."""
    path = engine.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
