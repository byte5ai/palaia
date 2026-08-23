"""Validation for GatewayConfig/VaultMountConfig/ProfileConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig


def test_vault_namespace_is_name_plus_memory_suffix() -> None:
    vault = VaultMountConfig(key="work", name="work", purpose="p")
    assert vault.namespace == "work_memory"


def test_vault_namespace_sanitizes_the_name() -> None:
    vault = VaultMountConfig(key="team-a", name="Team A!", purpose="p")
    assert vault.namespace == "Team_A_memory"


def test_tool_renames_reject_unknown_action() -> None:
    with pytest.raises(ValidationError):
        VaultMountConfig(key="work", name="work", tool_renames={"not-a-real-action": "x"})


def test_gateway_config_rejects_duplicate_vault_keys() -> None:
    vault = VaultMountConfig(key="work", name="work")
    with pytest.raises(ValidationError):
        GatewayConfig(vaults=[vault, vault])


def test_gateway_config_rejects_profile_referencing_unknown_vault() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig(
            vaults=[VaultMountConfig(key="work", name="work")],
            profiles=[ProfileConfig(path="default", vaults=["personal"])],
        )


def test_gateway_config_rejects_duplicate_profile_paths() -> None:
    vault = VaultMountConfig(key="work", name="work")
    profile = ProfileConfig(path="default", vaults=["work"])
    with pytest.raises(ValidationError):
        GatewayConfig(vaults=[vault], profiles=[profile, profile])


def test_gateway_config_vault_lookup() -> None:
    vault = VaultMountConfig(key="work", name="work")
    config = GatewayConfig(vaults=[vault])
    assert config.vault("work") is vault
    with pytest.raises(KeyError):
        config.vault("missing")
