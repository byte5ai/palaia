"""The ``backup:`` section (issue #297): what a hub accepts as a destination.

Every refusal here exists because the alternative is a config that
validates and then quietly never produces a backup — the one failure mode a
backup feature must not have.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from palaia_hub.config import BackupSettings, HubConfig, load_config


def test_a_hub_configures_no_targets_by_default() -> None:
    """SPEC-604's floor keeps working untouched: a hub writes an archive
    somewhere on its own only once an operator names that somewhere."""
    assert HubConfig().backup.targets == []


def test_a_local_directory_target_round_trips_from_yaml(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "backup:\n"
        "  targets:\n"
        "    - type: local_directory\n"
        "      name: nas\n"
        "      path: /mnt/nas/palaia-backups\n"
        "      keep_last: 14\n",
        encoding="utf-8",
    )

    config = load_config(tmp_path)

    (target,) = config.backup.targets
    assert (target.type, target.name, target.path, target.keep_last) == (
        "local_directory",
        "nas",
        "/mnt/nas/palaia-backups",
        14,
    )


def test_a_target_kind_that_is_designed_but_not_built_says_so(tmp_path: Path) -> None:
    """Issue #297 designs three targets; this release writes one. An
    operator who copies `git_remote` out of the issue is told it does not
    exist yet, not that they mistyped a literal."""
    (tmp_path / "config.yaml").write_text(
        "backup:\n  targets:\n    - type: git_remote\n      name: offsite\n      path: /x\n",
        encoding="utf-8",
    )

    with pytest.raises(Exception) as excinfo:
        load_config(tmp_path)

    message = str(excinfo.value)
    assert "not implemented in this release" in message
    assert "local_directory" in message


def test_a_relative_target_path_is_refused() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BackupSettings(targets=[{"name": "nas", "path": "backups"}])  # type: ignore[list-item]

    assert "must be absolute" in str(excinfo.value)


@pytest.mark.parametrize("name", ["Nas", "my backups", "nas/daily", "-nas", ""])
def test_a_name_that_is_not_a_usable_handle_is_refused(name: str) -> None:
    """The name is a REST path segment and a command-line argument."""
    with pytest.raises(ValidationError):
        BackupSettings(targets=[{"name": name, "path": "/mnt/nas"}])  # type: ignore[list-item]


def test_two_targets_cannot_share_a_name() -> None:
    with pytest.raises(ValidationError) as excinfo:
        BackupSettings(
            targets=[  # type: ignore[list-item]
                {"name": "nas", "path": "/mnt/a"},
                {"name": "nas", "path": "/mnt/b"},
            ]
        )

    assert "both named 'nas'" in str(excinfo.value)


def test_an_unknown_key_in_a_target_is_refused() -> None:
    """`extra="forbid"`, like every other settings model: a misspelled
    `keep_lastt` must not silently mean "keep everything forever"."""
    with pytest.raises(ValidationError):
        BackupSettings(targets=[{"name": "nas", "path": "/mnt/a", "keep_lastt": 3}])  # type: ignore[list-item]
