from pathlib import Path

import pytest

from palaia_hub.config import (
    ConfigError,
    HubConfig,
    RecallSettings,
    config_file_path,
    load_config,
    palaia_home,
)


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
    (tmp_path / "config.yaml").write_text("mode: locked\nport: 9000\n", encoding="utf-8")
    monkeypatch.setenv("PALAIA_MODE", "cloud")

    config = load_config(home=tmp_path)

    assert config.mode == "cloud"  # env wins over file
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


# --- SPEC-108: operating-mode auth policy -----------------------------------


def test_cloud_mode_defaults_to_auth_enabled_and_starts_fine(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\n", encoding="utf-8")

    config = load_config(home=tmp_path)

    assert config.mode == "cloud"
    assert config.auth_enabled is True


def test_cloud_mode_with_auth_disabled_fails_startup_with_exact_fix(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nauth_enabled: false\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert "auth_enabled: true" in message
    assert "PALAIA_AUTH_ENABLED" in message
    assert "Fix:" in message


def test_open_mode_with_auth_disabled_fails_startup(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: open\nauth_enabled: false\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    assert "Fix:" in str(excinfo.value)


def test_locked_mode_with_auth_disabled_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: locked\nauth_enabled: false\n", encoding="utf-8")

    config = load_config(home=tmp_path)

    assert config.auth_enabled is False


def test_auth_enabled_env_override_disables_and_fails_in_cloud_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\n", encoding="utf-8")
    monkeypatch.setenv("PALAIA_AUTH_ENABLED", "false")

    with pytest.raises(ConfigError):
        load_config(home=tmp_path)


def test_cloud_mode_with_wildcard_bind_host_fails_startup(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nhost: 0.0.0.0\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert "private" in message
    assert "Fix:" in message


def test_cloud_mode_with_public_ip_host_fails_startup(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nhost: 8.8.8.8\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(home=tmp_path)


def test_cloud_mode_with_tailscale_range_host_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: cloud\nhost: 100.64.1.2\n", encoding="utf-8")

    config = load_config(home=tmp_path)

    assert config.host == "100.64.1.2"


def test_open_mode_with_wildcard_bind_host_is_allowed(tmp_path: Path) -> None:
    # HubConfig itself still models the mode's semantics (no bind
    # restriction); load_config refuses it until the dashboard sign-in
    # exists (issue #242) — see test_open_mode_refused.py.
    config = HubConfig(mode="open", host="0.0.0.0", auth_enabled=True)

    assert config.mode == "open"
    assert config.host == "0.0.0.0"


def test_locked_mode_with_wildcard_bind_host_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: locked\nhost: 0.0.0.0\n", encoding="utf-8")

    config = load_config(home=tmp_path)

    assert config.host == "0.0.0.0"


# --- recall ranking weights (SPEC-106) -------------------------------------


def test_the_generated_default_file_round_trips_to_the_default_weights(
    tmp_path: Path,
) -> None:
    """The commented template must parse back to exactly the code defaults.

    Worth its own test: the template is prose, so a typo there would ship a
    config file that silently reranks every vault on first run.
    """
    from palaia_hub.recall import DEFAULT_WEIGHTS, weights_from_settings

    load_config(home=tmp_path)  # writes the template
    from_file = load_config(home=tmp_path)  # reads it back

    assert from_file.recall == RecallSettings()
    assert weights_from_settings(from_file.recall) == DEFAULT_WEIGHTS


def test_recall_weights_can_be_overridden_in_the_file(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "recall:\n  recency_weight: 0.9\n  half_life_days: 7\n", encoding="utf-8"
    )

    config = load_config(home=tmp_path)

    assert config.recall.recency_weight == 0.9
    assert config.recall.half_life_days == 7.0
    # Unset keys keep their defaults rather than zeroing out.
    assert config.recall.significance_weight == RecallSettings().significance_weight


def test_a_negative_recall_weight_is_rejected_with_the_key_named(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("recall:\n  recency_weight: -1\n", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        load_config(home=tmp_path)

    message = str(excinfo.value)
    assert "recall.recency_weight" in message
    assert "Fix:" in message


def test_an_unknown_recall_key_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("recall:\n  recncy_weight: 0.5\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(home=tmp_path)


# --------------------------------------------------------------- SPEC-301


def test_no_gateway_section_means_none(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)
    assert config.gateway is None


def test_gateway_section_parses_vaults_and_profiles(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "gateway:\n"
        "  vaults:\n"
        "    - key: work\n"
        "      name: Work\n"
        "      purpose: Work notes.\n"
        "      tool_renames:\n"
        "        search: find\n"
        "  profiles:\n"
        "    - path: default\n"
        "      label: Default\n"
        "      vaults: [work]\n"
        "      stash: true\n",
        encoding="utf-8",
    )

    config = load_config(home=tmp_path)

    assert config.gateway is not None
    assert config.gateway.vaults[0].key == "work"
    assert config.gateway.vaults[0].tool_renames == {"search": "find"}
    assert config.gateway.profiles[0].path == "default"
    assert config.gateway.profiles[0].label == "Default"
    assert config.gateway.profiles[0].vaults == ["work"]
    assert config.gateway.profiles[0].stash is True


def test_gateway_section_rejects_unknown_keys(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "gateway:\n  profiles:\n    - path: default\n      renmae: oops\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(home=tmp_path)


def test_oauth_profiles_is_deprecated_but_still_parses(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        "oauth:\n  enabled: true\n  issuer: https://hub.test\n  profiles: [alpha]\n",
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="oauth.profiles"):
        config = load_config(home=tmp_path)

    # Honored (parses, does not error) — just no longer read by anything.
    assert config.oauth.profiles == ["alpha"]


def test_oauth_without_profiles_set_warns_nothing(tmp_path: Path) -> None:
    import warnings

    (tmp_path / "config.yaml").write_text(
        "oauth:\n  enabled: true\n  issuer: https://hub.test\n", encoding="utf-8"
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_config(home=tmp_path)
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)
