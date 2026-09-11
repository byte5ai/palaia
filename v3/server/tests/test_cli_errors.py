"""Issue #396: every subcommand reports a broken config as one line, not a
traceback (only `serve` used to catch it)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.cli import _USER_FACING_ERRORS, main
from palaia_hub.vault import VaultConfigError, VaultNotFoundError


def test_a_broken_config_is_one_line_and_exit_code_1_for_every_subcommand(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text("oauth: [not, a, mapping]\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        main(["oauth", "clients"])

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("palaia-hub: ")
    assert "Traceback" not in err


def test_unknown_vaults_are_caller_facing_errors_too() -> None:
    assert VaultNotFoundError in _USER_FACING_ERRORS
    assert VaultConfigError in _USER_FACING_ERRORS
