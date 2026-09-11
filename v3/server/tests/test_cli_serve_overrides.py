"""Issue #327: ``palaia-hub serve --host/--port`` obey the operating-mode policy.

``model_copy(update=...)`` skips pydantic validators, so a ``mode: cloud``
config could be started on a wildcard bind through the CLI flag — the path
``deploy/entrypoint.sh`` actually takes. These tests never start a server:
``_serve_async`` is replaced so reaching it is itself the failure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub import cli
from palaia_hub.config import HubConfig, apply_config_overrides


def _home_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(body, encoding="utf-8")
    monkeypatch.setenv("PALAIA_HOME", str(home))
    return home


def test_cloud_mode_refuses_a_wildcard_host_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _home_with(tmp_path, monkeypatch, "mode: cloud\nhost: 127.0.0.1\nauth_enabled: true\n")

    async def _must_not_start(config: HubConfig) -> None:
        raise AssertionError("the hub started although the policy should have refused")

    monkeypatch.setattr(cli, "_serve_async", _must_not_start)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["serve", "--host", "0.0.0.0"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "configuration error" in err
    assert "private/VPN bind address" in err
    assert "Fix:" in err


def test_a_valid_override_is_applied_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home_with(tmp_path, monkeypatch, "mode: locked\n")
    seen: list[HubConfig] = []

    async def _record(config: HubConfig) -> None:
        seen.append(config)

    monkeypatch.setattr(cli, "_serve_async", _record)

    cli.main(["serve", "--host", "0.0.0.0", "--port", "9999"])

    assert len(seen) == 1
    assert seen[0].host == "0.0.0.0"
    assert seen[0].port == 9999


def test_apply_config_overrides_reports_out_of_range_values_as_config_errors() -> None:
    from palaia_hub.config import ConfigError

    config = HubConfig(mode="locked")
    with pytest.raises(ConfigError) as excinfo:
        apply_config_overrides(config, {"port": "not-a-port"})
    assert "port" in str(excinfo.value)
    assert apply_config_overrides(config, {}) is config
