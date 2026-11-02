"""Issue #609: a vault stays registered until its files are safely archived.

``VaultRegistry.archive`` used to unregister first and move afterwards, so a
failed move left the files in place but the vault gone — live and after a
restart — until someone registered it again by hand.
"""

from __future__ import annotations

import errno
import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import palaia_hub.vault.registry as registry_module
from palaia_hub.vault import VaultRegistry

pytestmark = pytest.mark.anyio

needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _task_vault(home: Path) -> VaultRegistry:
    registry = VaultRegistry(home)
    engine = await registry.create("task", home / "vaults" / "task", purpose="t", ephemeral=True)
    await engine.write_note("fact.md", title="Task fact", body="Must stay accessible")
    return registry


async def _still_there(registry: VaultRegistry, home: Path) -> None:
    assert "task" in registry.names()
    assert "task" in VaultRegistry(home).names()  # what a restart would load
    note = await (await registry.get("task")).read_note("fact.md")
    assert "Must stay accessible" in note.body
    assert (home / "vaults" / "task" / ".git").is_dir()


@needs_permissions
async def test_a_destination_that_cannot_be_written_leaves_the_vault_registered(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    registry = await _task_vault(home)
    registry.archive_dir.mkdir(parents=True)
    registry.archive_dir.chmod(0o500)
    try:
        with pytest.raises(PermissionError):
            await registry.archive("task")
    finally:
        registry.archive_dir.chmod(0o700)

    await _still_there(registry, home)
    assert not any(registry.archive_dir.iterdir())
    # Once the destination works again, closing goes through as usual.
    archived = await registry.archive("task")
    assert "task" not in registry.names()
    assert (archived / "fact.md").exists()
    await registry.aclose()


async def test_a_copy_across_filesystems_that_fails_halfway_is_undone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    registry = await _task_vault(home)
    real_copyfile = shutil.copyfile
    copied: list[str] = []

    def other_filesystem(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def run_out_of_space_halfway(src: str, dst: str, **kwargs: object) -> object:
        # Lets a few files through, then the destination fills up — the
        # archive directory now holds a partial copy.
        if len(copied) >= 5:
            raise OSError(errno.ENOSPC, "No space left on device")
        copied.append(dst)
        return real_copyfile(src, dst, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(registry_module.os, "rename", other_filesystem)
    monkeypatch.setattr(registry_module.shutil, "copyfile", run_out_of_space_halfway)
    with pytest.raises(OSError, match="No space left"):
        await registry.archive("task")
    monkeypatch.undo()
    assert len(copied) == 5  # the failure really came after a partial copy

    await _still_there(registry, home)
    assert not registry.archive_dir.exists() or not any(registry.archive_dir.iterdir())
    await registry.aclose()


async def test_a_copy_across_filesystems_archives_a_working_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    registry = await _task_vault(home)

    def other_filesystem(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(registry_module.os, "rename", other_filesystem)
    archived = await registry.archive("task")
    monkeypatch.undo()

    assert "task" not in registry.names()
    assert "task" not in VaultRegistry(home).names()
    assert not (home / "vaults" / "task").exists()
    assert (archived / "fact.md").exists()
    fsck = subprocess.run(  # noqa: S603
        ["git", "-C", str(archived), "fsck", "--full"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert fsck.returncode == 0, fsck.stderr


async def test_a_complete_copy_counts_even_if_the_original_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    home = tmp_path / "home"
    registry = await _task_vault(home)

    def other_filesystem(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    def cannot_remove(path: object, *args: object, **kwargs: object) -> None:
        raise OSError(errno.EBUSY, "Device or resource busy")

    monkeypatch.setattr(registry_module.os, "rename", other_filesystem)
    monkeypatch.setattr(registry_module.shutil, "rmtree", cannot_remove)
    with caplog.at_level(logging.WARNING, logger="palaia_hub.vault.registry"):
        archived = await registry.archive("task")
    monkeypatch.undo()

    # The archive is whole, so the vault is closed; the leftover is named.
    assert "task" not in registry.names()
    assert (archived / "fact.md").exists()
    assert "delete it by hand" in caplog.text
