"""A vault's git repository restores intact from a backup taken while it
changes (issue #605).

The archive is built while the hub keeps running: a write can commit, and
git's maintenance can repack, at any point of the walk. These tests pause
the real walk at the points where that used to break the archive, make the
change for real, and then check the restored repository the way git does —
``git fsck --full`` — not just that a gzip came out.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import palaia_hub.backup as backup


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(repo), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=check,
    )


def _vault(home: Path, commits: int = 3) -> Path:
    vault = home / "vaults" / "work"
    vault.mkdir(parents=True)
    _git(vault, "init", "--quiet", "--initial-branch=main")
    _git(vault, "config", "user.email", "test@example.invalid")
    _git(vault, "config", "user.name", "test")
    _git(vault, "config", "gc.autoDetach", "false")
    for number in range(commits):
        _commit(vault, f"note-{number}")
    return vault


def _commit(vault: Path, name: str) -> None:
    (vault / f"{name}.md").write_text(f"# {name}\n\n{name} body\n", encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "--quiet", "-m", f"add {name}")


def _restore(data: bytes, into: Path) -> Path:
    into.mkdir()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(into, filter="data")
    return into / "vaults" / "work"


def _fsck(repo: Path) -> subprocess.CompletedProcess[str]:
    return _git(repo, "fsck", "--full", check=False)


def _backup_pausing_at(
    home: Path,
    pause: Callable[[Path], bool],
    change: Callable[[], object],
    monkeypatch: pytest.MonkeyPatch,
) -> bytes:
    """Build the archive on a thread, stop the real walk where ``pause(path)``
    is true, run ``change()`` there for real, then let the walk go on."""
    reached = threading.Event()
    changed = threading.Event()
    walk = backup._sorted_walk

    def paused_walk(root: Path) -> Iterator[Path]:
        for path in walk(root):
            if not reached.is_set() and pause(path):
                reached.set()
                assert changed.wait(20), "the change never happened"
            yield path

    monkeypatch.setattr(backup, "_sorted_walk", paused_walk)
    result: dict[str, object] = {}

    def build() -> None:
        try:
            result["data"] = b"".join(backup.iter_archive_bytes(home))
        except BaseException as exc:  # noqa: BLE001 - reported to the test below
            result["error"] = exc

    builder = threading.Thread(target=build)
    builder.start()
    try:
        assert reached.wait(20), "the walk never reached the pause point"
        change()
    finally:
        changed.set()
        builder.join(30)
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["data"]  # type: ignore[return-value]


@pytest.mark.parametrize("pause_at", ["refs", "objects", "HEAD"])
def test_a_commit_during_the_backup_restores_a_valid_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pause_at: str
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    target = vault / ".git" / pause_at

    data = _backup_pausing_at(
        home, lambda path: path == target, lambda: _commit(vault, "during"), monkeypatch
    )

    restored = _restore(data, tmp_path / "restored")
    fsck = _fsck(restored)
    assert fsck.returncode == 0, fsck.stdout + fsck.stderr
    log = _git(restored, "log", "--format=%s").stdout.splitlines()
    assert "add note-2" in log  # the history up to the backup is all there


def test_git_maintenance_cannot_delete_objects_the_backup_still_has_to_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _git(vault, "gc", "--quiet")  # one pack on disk ...
    for number in range(3, 6):  # ... plus loose objects a repack would fold in
        _commit(vault, f"note-{number}")
    old_packs = sorted((vault / ".git/objects/pack").glob("*.pack"))
    assert old_packs
    gc_while_reading: dict[str, subprocess.CompletedProcess[str]] = {}

    data = _backup_pausing_at(
        home,
        lambda path: path == old_packs[0],
        lambda: gc_while_reading.setdefault("gc", _git(vault, "gc", "--quiet", check=False)),
        monkeypatch,
    )

    gc = gc_while_reading["gc"]
    assert gc.returncode != 0 and "already running" in gc.stderr, gc.stderr
    restored = _restore(data, tmp_path / "restored")
    fsck = _fsck(restored)
    assert fsck.returncode == 0, fsck.stdout + fsck.stderr
    assert len(_git(restored, "log", "--format=%s").stdout.splitlines()) == 6
    # The backup handed the lock back: maintenance works again right away.
    assert not (vault / ".git/gc.pid").exists()
    assert _git(vault, "gc", "--quiet", check=False).returncode == 0


def test_the_archive_holds_no_git_lock_files_or_temporary_objects(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    (vault / ".git/index.lock").write_text("", encoding="utf-8")
    (vault / ".git/objects/tmp_obj_abc123").write_bytes(b"half-written")

    data = b"".join(backup.iter_archive_bytes(home))

    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        names = archive.getnames()
    assert "vaults/work/.git/HEAD" in names
    assert not [name for name in names if name.endswith(".lock")]
    assert not [name for name in names if name.endswith("gc.pid")]
    assert not [name for name in names if "tmp_obj_" in name]


def test_a_gc_already_running_is_waited_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "_GIT_GC_POLL_SECONDS", 0.05)
    home = tmp_path / "home"
    vault = _vault(home)
    running = subprocess.Popen(["sleep", "30"])  # noqa: S607 - stands in for git gc
    try:
        (vault / ".git/gc.pid").write_text(
            f"{running.pid} {socket.gethostname()}", encoding="utf-8"
        )

        def gc_finishes() -> None:
            # Killed *and reaped*: an unreaped child still answers kill(pid, 0).
            running.kill()
            running.wait()

        threading.Timer(1.0, gc_finishes).start()
        started = time.monotonic()
        data = b"".join(backup.iter_archive_bytes(home))
        waited = time.monotonic() - started
    finally:
        running.kill()
        running.wait()
    assert waited >= 0.9
    assert _fsck(_restore(data, tmp_path / "restored")).returncode == 0


def test_a_gc_that_does_not_finish_fails_the_backup_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "_GIT_GC_WAIT_SECONDS", 0.3)
    monkeypatch.setattr(backup, "_GIT_GC_POLL_SECONDS", 0.05)
    home = tmp_path / "home"
    vault = _vault(home)
    # A live process on this host holds git's gc lock — like a gc mid-repack.
    (vault / ".git/gc.pid").write_text(f"{os.getpid()} {socket.gethostname()}", encoding="utf-8")

    with pytest.raises(backup.BackupError, match="git maintenance is still running in work"):
        b"".join(backup.iter_archive_bytes(home))
    # Someone else's lock is left alone.
    assert (vault / ".git/gc.pid").exists()


def test_a_stale_gc_lock_does_not_hold_up_the_backup(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    finished = subprocess.Popen(["true"])  # noqa: S607
    finished.wait()
    (vault / ".git/gc.pid").write_text(f"{finished.pid} {socket.gethostname()}", encoding="utf-8")

    started = time.monotonic()
    data = b"".join(backup.iter_archive_bytes(home))

    assert time.monotonic() - started < backup._GIT_GC_WAIT_SECONDS / 2
    assert _fsck(_restore(data, tmp_path / "restored")).returncode == 0
