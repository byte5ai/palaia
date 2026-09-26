"""``palaia-hub backup`` (issue #317): the dashboard's archive, written locally.

The route refuses on a hub whose dashboard has no sign-in (the locked-mode
default), so the CLI is the way such a hub is backed up — same bytes, same
exclusions, written on the host.
"""

from __future__ import annotations

import json
import stat
import tarfile
from pathlib import Path

import pytest

from palaia_hub.backup_schedule import STATUS_FILENAME
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


# --------------------------------- writing to a configured target (#297)


def _home_with_target(tmp_path: Path, destination: Path, *, keep_last: int | None = 7) -> Path:
    """A hub home whose `config.yaml` names one local-directory target."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    keep = "null" if keep_last is None else str(keep_last)
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "backup:\n"
        "  targets:\n"
        "    - type: local_directory\n"
        "      name: nas\n"
        f"      path: {destination}\n"
        f"      keep_last: {keep}\n",
        encoding="utf-8",
    )
    return home


def test_backup_to_a_configured_target_writes_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI runs the same targets the dashboard does — so a hub whose
    dashboard has no sign-in has the whole feature, not half of it."""
    destination = tmp_path / "nas"
    home = _home_with_target(tmp_path, destination)
    monkeypatch.setenv("PALAIA_HOME", str(home))

    main(["backup", "--target", "nas"])

    written = list(destination.glob("palaia-backup-*.tar.gz"))
    assert len(written) == 1
    assert stat.S_IMODE(written[0].stat().st_mode) == 0o600
    printed = capsys.readouterr().out
    assert str(destination) in printed
    assert "as private as a password" in printed


def test_all_targets_writes_to_every_configured_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    first = tmp_path / "nas"
    second = tmp_path / "usb"
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "backup:\n"
        "  targets:\n"
        f"    - {{type: local_directory, name: nas, path: {first}}}\n"
        f"    - {{type: local_directory, name: usb, path: {second}}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PALAIA_HOME", str(home))

    main(["backup", "--all-targets"])

    assert len(list(first.glob("palaia-backup-*.tar.gz"))) == 1
    assert len(list(second.glob("palaia-backup-*.tar.gz"))) == 1


def test_listing_targets_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "nas"
    home = _home_with_target(tmp_path, destination, keep_last=3)
    monkeypatch.setenv("PALAIA_HOME", str(home))

    main(["backup", "--list-targets"])

    printed = capsys.readouterr().out
    assert "nas" in printed
    assert str(destination) in printed
    assert "keeps the newest 3" in printed
    assert "Not scheduled" in printed
    assert not destination.exists()


def test_listing_targets_shows_the_schedule_and_what_the_hub_last_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #438: on a hub whose dashboard has no sign-in, this is where
    the operator sees whether the schedule is actually producing backups."""
    destination = tmp_path / "nas"
    home = _home_with_target(tmp_path, destination)
    config = home / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("backup:\n", "backup:\n  interval_hours: 12\n"),
        encoding="utf-8",
    )
    (home / STATUS_FILENAME).write_text(
        json.dumps(
            {
                "version": 1,
                "last_pass_at": 1_800_000_000,
                "targets": {
                    "nas": {
                        "finished_at": 1_800_000_000,
                        "ok": False,
                        "trigger": "schedule",
                        "reason": "the share is not mounted",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PALAIA_HOME", str(home))

    main(["backup", "--list-targets"])

    printed = capsys.readouterr().out
    assert "every 12 h" in printed
    assert "last run by the hub (schedule), 2027-01-15 08:00 UTC" in printed
    assert "FAILED: the share is not mounted" in printed


def test_an_unknown_target_name_is_a_one_line_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home_with_target(tmp_path, tmp_path / "nas")
    monkeypatch.setenv("PALAIA_HOME", str(home))

    with pytest.raises(SystemExit) as excinfo:
        main(["backup", "--target", "usb"])

    assert excinfo.value.code == 1
    assert "no destination named 'usb'" in capsys.readouterr().err


def test_a_failing_target_exits_non_zero_after_trying_the_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cron entry wrapping this has to notice — and a local disk should
    still get its copy when a mounted share is gone."""
    home = tmp_path / "home"
    home.mkdir()
    good = tmp_path / "usb"
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "backup:\n"
        "  targets:\n"
        f"    - {{type: local_directory, name: broken, path: {home / 'inside'}}}\n"
        f"    - {{type: local_directory, name: usb, path: {good}}}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PALAIA_HOME", str(home))

    with pytest.raises(SystemExit) as excinfo:
        main(["backup", "--all-targets"])

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "inside the hub's own data directory" in captured.err
    assert len(list(good.glob("palaia-backup-*.tar.gz"))) == 1


def test_out_and_target_cannot_be_combined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _home_with_target(tmp_path, tmp_path / "nas")
    monkeypatch.setenv("PALAIA_HOME", str(home))

    with pytest.raises(SystemExit):
        main(["backup", "--target", "nas", "--out", str(tmp_path / "x.tar.gz")])

    assert "pass one or the other" in capsys.readouterr().err


def test_a_plain_backup_never_creates_a_config_file_in_the_home_it_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`load_config` writes a default `config.yaml` when none exists —
    taking a backup must not mutate the home it is about to archive."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PALAIA_HOME", str(home))

    main(["backup", "--out", str(tmp_path / "hub.tar.gz")])

    assert not (home / "config.yaml").exists()
