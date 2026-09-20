"""Backup targets (issue #297): the abstraction's one invariant, and the
local-directory target end to end.

Two things are worth pinning here. The first is the rule the owner decision
states in prose — the full archive never reaches a destination that is not
secret-safe — which this package expresses as a class-level invariant every
target declares, so the test for it is a deliberately wrong target class
that must fail before it writes anything. The second is that the archive a
target leaves behind is a *real, restorable* one: same bytes as the
download, same exclusions, unpackable.
"""

from __future__ import annotations

import stat
import tarfile
from pathlib import Path
from typing import Any

import pytest

from palaia_hub.backup_targets import (
    ARCHIVE_GLOB,
    FAILED_EVENT,
    SUCCEEDED_EVENT,
    BackupTarget,
    BackupTargetError,
    LocalDirectoryTarget,
    build_targets,
    run_target,
)
from palaia_hub.config import BackupSettings, LocalDirectoryBackupTarget


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A hub home with something recognizable in it."""
    home = tmp_path / "home"
    (home / "vaults" / "work").mkdir(parents=True)
    (home / "vaults" / "work" / "note.md").write_text("# Hi\n", encoding="utf-8")
    (home / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    return home


# ------------------------------------------------- the abstraction's invariant


class _LeakyTarget(BackupTarget):
    """A target class written wrong on purpose: it moves the full archive
    (secrets and their key) to somewhere nobody declared safe for it."""

    kind = "leaky"
    carries_full_archive = True
    secret_safe = False

    @property
    def destination(self) -> str:
        return "somewhere://else"

    def _write(self, home: Path) -> tuple[str, int, tuple[str, ...]]:  # pragma: no cover
        raise AssertionError("run() must refuse before the archive is ever built")


def test_a_target_that_would_move_the_full_archive_somewhere_unsafe_is_refused(
    home: Path,
) -> None:
    """Issue #297's fixed design point, enforced in code rather than in a
    comment: the guard runs before `_write`, so a misdeclared target cannot
    leak on its way to failing."""
    with pytest.raises(BackupTargetError) as excinfo:
        _LeakyTarget(name="oops").run(home)

    message = str(excinfo.value)
    assert "not marked secret-safe" in message
    assert "oops" in message


def test_the_local_directory_target_declares_what_it_moves() -> None:
    assert LocalDirectoryTarget.carries_full_archive is True
    assert LocalDirectoryTarget.secret_safe is True


# ------------------------------------------------ the local-directory target


def test_it_writes_a_restorable_archive_into_the_directory(home: Path, tmp_path: Path) -> None:
    destination = tmp_path / "nas" / "backups"
    target = LocalDirectoryTarget(name="nas", directory=destination, keep_last=None)

    run = target.run(home)

    written = destination / run.artifact
    assert written.is_file()
    assert run.bytes_written == written.stat().st_size
    assert run.target == "nas"
    assert run.kind == "local_directory"
    assert run.destination == str(destination)
    with tarfile.open(written, mode="r:gz") as tar:
        names = tar.getnames()
    assert "config.yaml" in names
    assert "vaults/work/note.md" in names


def test_the_archive_is_owner_only_and_no_partial_file_is_left_behind(
    home: Path, tmp_path: Path
) -> None:
    """Mode 0600 like `palaia-hub backup`'s own output — this file can act
    as the hub — and the `.part` sibling is gone once the run completed."""
    destination = tmp_path / "backups"
    target = LocalDirectoryTarget(name="nas", directory=destination, keep_last=None)

    run = target.run(home)

    written = destination / run.artifact
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert list(destination.glob("*.part")) == []


def test_a_directory_inside_the_hub_home_is_refused(home: Path) -> None:
    """A hub backing itself up into itself: every archive would contain
    every archive before it, and none of them would survive losing that
    directory."""
    target = LocalDirectoryTarget(name="inside", directory=home / "backups", keep_last=None)

    with pytest.raises(BackupTargetError) as excinfo:
        target.run(home)

    assert "inside the hub's own data directory" in str(excinfo.value)
    assert not (home / "backups").exists()


def test_a_destination_that_cannot_be_written_fails_with_the_path_named(
    home: Path, tmp_path: Path
) -> None:
    """The unmounted-share case: the error names the directory, and no
    half-written file is left looking like an archive."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    target = LocalDirectoryTarget(name="nas", directory=blocked / "backups", keep_last=None)

    try:
        with pytest.raises(BackupTargetError) as excinfo:
            target.run(home)
    finally:
        blocked.chmod(0o700)

    assert str(blocked / "backups") in str(excinfo.value)


# ----------------------------------------------------------------- retention


def _stale_archives(directory: Path, count: int) -> list[Path]:
    """`count` archives named the way `archive_filename` names them, oldest
    first — the timestamps are fixed rather than real, which is the point:
    retention must order by the name, not by an mtime a copy can rewrite."""
    directory.mkdir(parents=True, exist_ok=True)
    made = []
    for index in range(count):
        path = directory / f"palaia-backup-2026010{index}T000000Z.tar.gz"
        path.write_bytes(b"old")
        made.append(path)
    return made


def test_retention_keeps_the_newest_and_deletes_the_rest(home: Path, tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    old = _stale_archives(destination, 4)
    target = LocalDirectoryTarget(name="nas", directory=destination, keep_last=2)

    run = target.run(home)

    # Three of the five (four stale plus the fresh one) go; the fresh
    # archive and the newest stale one stay.
    assert run.pruned == tuple(path.name for path in old[:3])
    remaining = sorted(path.name for path in destination.glob(ARCHIVE_GLOB))
    assert remaining == sorted([old[3].name, run.artifact])


def test_retention_never_touches_a_file_this_hub_did_not_write(
    home: Path, tmp_path: Path
) -> None:
    """An operator's directory is theirs. Only files matching the archive
    naming are ever candidates — a backup feature that deletes a stranger's
    file is a data-loss bug."""
    destination = tmp_path / "backups"
    _stale_archives(destination, 3)
    theirs = destination / "important.tar.gz"
    theirs.write_bytes(b"not ours")
    note = destination / "README.txt"
    note.write_bytes(b"also not ours")

    LocalDirectoryTarget(name="nas", directory=destination, keep_last=1).run(home)

    assert theirs.is_file()
    assert note.is_file()


def test_keep_last_none_keeps_every_archive(home: Path, tmp_path: Path) -> None:
    destination = tmp_path / "backups"
    _stale_archives(destination, 3)

    run = LocalDirectoryTarget(name="nas", directory=destination, keep_last=None).run(home)

    assert run.pruned == ()
    assert len(list(destination.glob(ARCHIVE_GLOB))) == 4


# -------------------------------------------------------------------- events


def test_a_run_reports_success_on_the_event_bus(home: Path, tmp_path: Path) -> None:
    published: list[tuple[str, dict[str, Any]]] = []
    target = LocalDirectoryTarget(name="nas", directory=tmp_path / "backups", keep_last=None)

    run = run_target(target, home, publish=lambda event, data: published.append((event, data)))

    assert [event for event, _ in published] == [SUCCEEDED_EVENT]
    assert published[0][1] == run.to_json()


def test_a_failed_run_is_never_silent(home: Path, tmp_path: Path) -> None:
    """Issue #297: "failures surface as events/notifications, never
    silently" — and the caller still sees the exception."""
    published: list[tuple[str, dict[str, Any]]] = []
    target = LocalDirectoryTarget(name="inside", directory=home / "backups", keep_last=None)

    with pytest.raises(BackupTargetError):
        run_target(target, home, publish=lambda event, data: published.append((event, data)))

    assert [event for event, _ in published] == [FAILED_EVENT]
    assert published[0][1]["target"] == "inside"
    assert "inside the hub's own data directory" in published[0][1]["reason"]


def test_a_broken_event_bus_never_turns_a_finished_backup_into_a_failure(
    home: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "backups"

    def explode(event: str, data: dict[str, Any]) -> None:
        raise RuntimeError("the bus is down")

    run = run_target(
        LocalDirectoryTarget(name="nas", directory=destination, keep_last=None),
        home,
        publish=explode,
    )

    assert (destination / run.artifact).is_file()


# ------------------------------------------------------- building from config


def test_targets_are_built_from_config_in_order() -> None:
    settings = BackupSettings(
        targets=[
            LocalDirectoryBackupTarget(name="nas", path="/mnt/nas/backups", keep_last=3),
            LocalDirectoryBackupTarget(name="usb", path="/mnt/usb", keep_last=None),
        ]
    )

    targets = build_targets(settings)

    assert list(targets) == ["nas", "usb"]
    assert targets["nas"].describe() == {
        "name": "nas",
        "kind": "local_directory",
        "destination": "/mnt/nas/backups",
        "carries_full_archive": True,
        "secret_safe": True,
        "keep_last": 3,
    }


def test_a_home_relative_target_path_is_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/someone")
    settings = BackupSettings(targets=[LocalDirectoryBackupTarget(name="disk", path="~/backups")])

    target = build_targets(settings)["disk"]

    assert target.destination == "/home/someone/backups"


def test_no_backup_section_configures_no_targets() -> None:
    assert build_targets(BackupSettings()) == {}
