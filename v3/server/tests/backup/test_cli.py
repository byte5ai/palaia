"""``palaia-hub backup`` (issue #317): the dashboard's archive, written locally.

The route refuses on a hub whose dashboard has no sign-in (the locked-mode
default), so the CLI is the way such a hub is backed up — same bytes, same
exclusions, written on the host.
"""

from __future__ import annotations

import stat
import tarfile
from pathlib import Path

import pytest

from palaia_hub.cli import main


def test_backup_writes_the_archive_where_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    (home / "vaults" / "work").mkdir(parents=True)
    (home / "vaults" / "work" / "note.md").write_text("# Hi\n", encoding="utf-8")
    (home / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    monkeypatch.setenv("PALAIA_HOME", str(home))
    out = tmp_path / "out" / "hub.tar.gz"

    main(["backup", "--out", str(out)])

    assert out.is_file()
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert not out.with_name(out.name + ".part").exists()
    with tarfile.open(out, mode="r:gz") as tar:
        names = tar.getnames()
    assert "config.yaml" in names
    assert "vaults/work/note.md" in names
    printed = capsys.readouterr().out
    assert str(out) in printed
    assert "store it like a password" in printed


def test_backup_into_a_directory_picks_a_timestamped_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("mode: locked\n", encoding="utf-8")
    monkeypatch.setenv("PALAIA_HOME", str(home))
    target_dir = tmp_path / "backups"
    target_dir.mkdir()

    main(["backup", "--out", str(target_dir)])

    written = list(target_dir.glob("palaia-backup-*.tar.gz"))
    assert len(written) == 1
