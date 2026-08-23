from pathlib import Path

import pytest

from palaia_hub.config import ConfigError, config_file_path, load_config, palaia_home


def test_defaults_when_no_file_and_creates_one(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)

    assert config.mode == "locked"
    assert config.host == "127.0.0.1"
    assert config.port == 8420
    assert config.log_level == "info"
    assert config.log_format == "human"
    assert (tmp_path / "config.yaml").exists()


def test_file_overrides_defaults(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nport: 9000\n", encoding="utf-8")

    config = load_config(home=tmp_path)

    assert config.mode == "cloud"
    assert config.port == 9000
    # Untouched keys keep their defaults.
    assert config.log_level == "info"


def test_env_overrides_file_which_overrides_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nport: 9000\n", encoding="utf-8")
    monkeypatch.setenv("PALAIA_MODE", "open")

    config = load_config(home=tmp_path)

    assert config.mode == "open"  # env wins over file
    assert config.port == 9000  # file still wins over default (no env override)


def test_env_var_port_is_coerced_to_int(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALAIA_PORT", "9999")

    config = load_config(home=tmp_path)

    assert config.port == 9999


def test_invalid_mode_reports_file_key_and_fix(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: bogus\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert str(tmp_path / "config.yaml") in message
    assert "mode" in message
    assert "Fix" in message


def test_invalid_env_override_also_reports_key_and_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PALAIA_MODE", "not-a-mode")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert "mode" in message
    assert "Fix" in message


def test_malformed_yaml_reports_file_and_fix(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: [unterminated\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert str(tmp_path / "config.yaml") in message
    assert "Fix" in message


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    assert "mapping" in str(excinfo.value)


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("not_a_real_setting: 1\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(home=tmp_path)


def test_config_file_path_uses_given_home(tmp_path: Path) -> None:
    assert config_file_path(tmp_path) == tmp_path / "config.yaml"


def test_palaia_home_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))

    assert palaia_home() == tmp_path


def test_palaia_home_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALAIA_HOME", "~/palaia-test-home")

    assert "~" not in str(palaia_home())
