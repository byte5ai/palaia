"""``palaia-hub doctor`` end to end on a real hub home (issue #296)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from palaia_hub.cli import main
from palaia_hub.config import config_file_path


@pytest.fixture(autouse=True)
def hub_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PALAIA_HOME", str(home))
    return home


def test_a_fresh_hub_gets_a_readable_report_and_exit_code_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main(["doctor"])

    out = capsys.readouterr().out
    assert out.startswith("palaia-hub doctor")
    # A hub with no vault and no token: two things to do, both named.
    assert "no-vaults" in out
    assert "no-way-in" in out
    assert "Fix: " in out
    # And the part that genuinely could not be checked is not called healthy.
    assert "Search — not checked:" in out


def test_diagnosing_a_hub_never_writes_to_it(hub_home: Path) -> None:
    """Every other subcommand creates a default config.yaml on the way past;
    a diagnosis must not change the thing it is diagnosing."""
    main(["doctor"])

    assert not config_file_path(hub_home).exists()
    assert list(hub_home.iterdir()) == []


def test_the_json_report_carries_every_check(capsys: pytest.CaptureFixture[str]) -> None:
    main(["doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "warning"
    assert [check["id"] for check in payload["checks"]] == [
        "config",
        "vaults",
        "search",
        "clients",
        "storage",
    ]
    assert payload["counts"]["error"] == 0
    vaults = next(check for check in payload["checks"] if check["id"] == "vaults")
    assert vaults["findings"][0]["fix"]


def test_an_error_finding_makes_the_command_exit_1(
    hub_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_file_path(hub_home).write_text(
        "mode: locked\nexposure:\n  public_url: http://hub.lan\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["doctor"])

    assert exit_info.value.code == 1
    assert "public-address-plaintext" in capsys.readouterr().out


def test_fix_performs_the_safe_repair_and_says_what_it_did(
    hub_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = config_file_path(hub_home)
    path.write_text("mode: locked\n", encoding="utf-8")
    path.chmod(0o644)

    main(["doctor", "--fix"])

    out = capsys.readouterr().out
    assert "config-readable-by-others" in out
    assert "palaia-hub doctor --fix" in out
    assert "Re-run the doctor to confirm." in out
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_fix_on_a_healthy_hub_changes_nothing(
    hub_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["doctor", "--fix"])

    assert "Nothing needed fixing." in capsys.readouterr().out
    assert not config_file_path(hub_home).exists()
