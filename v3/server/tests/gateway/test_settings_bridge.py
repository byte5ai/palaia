"""SPEC-301: config.yaml's ``gateway:`` section ↔ the gateway's own shapes."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from palaia_hub.config import (
    GatewayProfileSettings,
    GatewaySettings,
    GatewayVaultSettings,
    HubConfig,
)
from palaia_hub.gateway.config import ProfileConfig, VaultMountConfig
from palaia_hub.gateway.settings_bridge import (
    GatewaySettingsError,
    apply_vault_overrides,
    persist_gateway_settings,
    render_gateway_section,
    resolve_full_gateway_profiles,
    resolve_profiles,
)


def test_gateway_vault_settings_matches_vault_mount_config_fields() -> None:
    """config.py's fastmcp-free duplicate must not drift from the shape it
    stands in for (see ``GatewayVaultSettings``'s docstring)."""
    assert set(GatewayVaultSettings.model_fields) == set(VaultMountConfig.model_fields)


def test_gateway_profile_settings_matches_profile_config_fields() -> None:
    assert set(GatewayProfileSettings.model_fields) == set(ProfileConfig.model_fields)


def test_apply_vault_overrides_none_settings_is_a_no_op() -> None:
    mounts = [VaultMountConfig(key="work", name="work", purpose="Work.")]
    assert apply_vault_overrides(mounts, None) == mounts


def test_apply_vault_overrides_overlays_matching_keys() -> None:
    mounts = [
        VaultMountConfig(key="work", name="work", purpose="Work."),
        VaultMountConfig(key="home", name="home", purpose="Home."),
    ]
    settings = GatewaySettings(
        vaults=[
            GatewayVaultSettings(
                key="work", name="Work Notes", tool_renames={"search": "find"}
            )
        ]
    )

    result = apply_vault_overrides(mounts, settings)

    work = next(m for m in result if m.key == "work")
    home = next(m for m in result if m.key == "home")
    assert work.name == "Work Notes"
    assert work.purpose == "Work."  # untouched (override left purpose unset)
    assert work.tool_renames == {"search": "find"}
    assert home.name == "home"  # untouched: no override for this key


def test_resolve_profiles_default_when_no_section() -> None:
    profiles = resolve_profiles(None, ["work", "home"], default_profile="default")
    assert profiles == [ProfileConfig(path="default", vaults=["work", "home"])]


def test_resolve_profiles_default_when_no_vaults_yet() -> None:
    assert resolve_profiles(None, [], default_profile="default") == []


def test_resolve_profiles_uses_configured_shape() -> None:
    settings = GatewaySettings(
        profiles=[
            GatewayProfileSettings(path="alpha", vaults=["work"], stash=True),
            GatewayProfileSettings(path="beta", vaults=["home"]),
        ]
    )

    profiles = resolve_profiles(settings, ["work", "home"], default_profile="default")

    assert [p.path for p in profiles] == ["alpha", "beta"]
    assert profiles[0].stash is True
    assert profiles[1].stash is False


def test_resolve_profiles_unknown_vault_raises() -> None:
    settings = GatewaySettings(
        profiles=[GatewayProfileSettings(path="alpha", vaults=["ghost"])]
    )

    with pytest.raises(GatewaySettingsError, match="ghost"):
        resolve_profiles(settings, ["work"], default_profile="default")


def test_resolve_full_gateway_profiles_adds_curator_profile_when_enabled() -> None:
    config = HubConfig(curator={"enabled": True})

    profiles = resolve_full_gateway_profiles(config, ["work"], default_profile="default")

    paths = {p.path for p in profiles}
    assert paths == {"default", "curator"}


def test_resolve_full_gateway_profiles_no_curator_profile_without_vaults() -> None:
    config = HubConfig(curator={"enabled": True})
    assert resolve_full_gateway_profiles(config, [], default_profile="default") == []


def test_render_and_persist_round_trips(tmp_path: Path) -> None:
    settings = GatewaySettings(
        vaults=[GatewayVaultSettings(key="work", tool_renames={"search": "find"})],
        profiles=[GatewayProfileSettings(path="default", vaults=["work"], stash=True)],
    )
    path = tmp_path / "config.yaml"
    path.write_text("mode: locked\n# a comment that must survive\n", encoding="utf-8")

    persist_gateway_settings(path, settings)
    text = path.read_text(encoding="utf-8")

    assert "# a comment that must survive" in text
    reloaded = yaml.safe_load(text)
    assert reloaded["gateway"]["vaults"][0]["key"] == "work"
    assert reloaded["gateway"]["profiles"][0]["stash"] is True
    # Re-parses cleanly as a real HubConfig too.
    from palaia_hub.config import load_config

    config = load_config(home=tmp_path)
    assert config.gateway is not None
    assert config.gateway.profiles[0].path == "default"


def test_persist_gateway_settings_replaces_an_existing_section(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "mode: locked\ngateway:\n  vaults: []\n  profiles:\n    - path: old\n      vaults: []\n"
        "curator:\n  enabled: false\n",
        encoding="utf-8",
    )

    persist_gateway_settings(
        path,
        GatewaySettings(profiles=[GatewayProfileSettings(path="new", vaults=[])]),
    )
    text = path.read_text(encoding="utf-8")

    assert "path: old" not in text
    assert "path: new" in text
    # Sections after the one being replaced are untouched.
    assert "curator:" in text
    assert "enabled: false" in text


def test_render_gateway_section_empty_settings_is_valid_yaml() -> None:
    body = render_gateway_section(GatewaySettings())
    parsed = yaml.safe_load(f"gateway:\n{body}")
    # `upstreams` joined the section in SPEC-302; an empty list means
    # "no external servers connected", which is every hub until someone
    # connects one.
    assert parsed == {"gateway": {"vaults": [], "profiles": [], "upstreams": []}}
