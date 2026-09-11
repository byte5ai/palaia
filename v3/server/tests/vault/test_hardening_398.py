"""Issue #398: vault-layer footguns the rc1 review found by reading."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from vault_helpers import EngineFactory

from palaia_hub.vault import (
    InvalidPathError,
    NoteNotFoundError,
    PermalinkConflictError,
    VaultEngine,
    VaultError,
    VaultRegistry,
)
from palaia_hub.vault.atomic import TEMP_SUFFIX

pytestmark = pytest.mark.anyio


async def test_a_frontmatter_permalink_is_checked_like_the_permalink_argument(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine()
    await engine.write_note("projects/one.md", body="x", title="One")
    taken = engine.catalog["projects/one.md"].permalink
    assert taken

    with pytest.raises(VaultError, match="not canonical"):
        await engine.write_note(
            "notes/two.md", body="y", title="Two", frontmatter={"permalink": "Not Canonical"}
        )
    with pytest.raises(PermalinkConflictError):
        await engine.write_note(
            "notes/three.md", body="z", title="Three", frontmatter={"permalink": taken}
        )
    # A note restating its *own* permalink through frontmatter is fine.
    current = await engine.read_note("projects/one.md")
    await engine.edit_note(
        "projects/one.md",
        body="x2",
        frontmatter={"permalink": taken},
        expected_checksum=current.checksum,
    )


async def test_engine_private_directories_are_refused_at_any_depth(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine()
    with pytest.raises(InvalidPathError):
        await engine.write_note("notes/.git/hidden.md", body="x", title="Hidden")
    with pytest.raises(InvalidPathError):
        await engine.write_note("notes/.palaia/hidden.md", body="x", title="Hidden")
    with pytest.raises(NoteNotFoundError):
        await engine.list_dir(".git")
    with pytest.raises(NoteNotFoundError):
        await engine.list_dir("./.palaia")


async def test_a_symlink_pointing_outside_the_vault_does_not_break_open(
    tmp_path: Path, make_engine: EngineFactory
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "leak.md").write_text("---\ntitle: Leak\n---\nnot ours\n", encoding="utf-8")
    engine = await make_engine()
    await engine.write_note("notes/real.md", body="ours", title="Real")
    (engine.root / "linked").symlink_to(outside, target_is_directory=True)
    (engine.root / "notes" / "leak-link.md").symlink_to(outside / "leak.md")
    await engine.close()

    reopened = VaultEngine(engine.root, "work")
    await reopened.open()
    try:
        paths = set(reopened.catalog)
        assert "notes/real.md" in paths
        assert not any("leak" in path or path.startswith("linked/") for path in paths)
    finally:
        await reopened.close()


async def test_open_leaves_a_fresh_temp_file_alone_but_sweeps_old_residue(
    make_engine: EngineFactory,
) -> None:
    engine = await make_engine()
    await engine.close()
    fresh = engine.root / f"notes/in-flight{TEMP_SUFFIX}"
    fresh.parent.mkdir(exist_ok=True)
    fresh.write_text("another process is writing this", encoding="utf-8")
    stale = engine.root / f"notes/crash-residue{TEMP_SUFFIX}"
    stale.write_text("left behind long ago", encoding="utf-8")
    old = time.time() - 600
    os.utime(stale, (old, old))

    reopened = VaultEngine(engine.root, "work")
    await reopened.open()
    try:
        assert fresh.exists(), "a seconds-old temp file may be another process's write"
        assert not stale.exists(), "minutes-old residue is still swept"
    finally:
        await reopened.close()


async def test_two_concurrent_first_callers_share_one_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = VaultRegistry(tmp_path / "home")
    await registry.create("work", tmp_path / "work", purpose="test")
    # Forget the engine create() opened so get() has to open one.
    registry._engines.clear()
    opens = 0
    original = VaultEngine.open

    async def counting(self: VaultEngine, *args: object, **kwargs: object) -> None:
        nonlocal opens
        opens += 1
        await asyncio.sleep(0.01)  # widen the window two callers used to fall into
        await original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(VaultEngine, "open", counting)
    first, second = await asyncio.gather(registry.get("work"), registry.get("work"))
    assert first is second
    assert opens == 1
