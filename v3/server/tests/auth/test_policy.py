"""``check_gateway_auth_policy``: the built-gateway half of the mode/auth check."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.auth.policy import AuthPolicyError, check_gateway_auth_policy
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.wiring import build_profile_verifiers
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService


def _gateway_config() -> GatewayConfig:
    return GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )


def test_locked_mode_allows_a_gateway_with_no_auth_at_all() -> None:
    gateway = build_gateway(_gateway_config(), {"work": FakeVaultService()})

    check_gateway_auth_policy("locked", gateway.profile_servers)  # does not raise


def test_cloud_mode_refuses_a_profile_with_no_verifier(tmp_path: Path) -> None:
    gateway = build_gateway(_gateway_config(), {"work": FakeVaultService()})

    with pytest.raises(AuthPolicyError, match="default"):
        check_gateway_auth_policy("cloud", gateway.profile_servers)


def test_open_mode_refuses_a_profile_with_no_verifier() -> None:
    gateway = build_gateway(_gateway_config(), {"work": FakeVaultService()})

    with pytest.raises(AuthPolicyError):
        check_gateway_auth_policy("open", gateway.profile_servers)


def test_cloud_mode_accepts_a_gateway_with_every_profile_authenticated(
    tmp_path: Path,
) -> None:
    store = TokenStore(home=tmp_path)
    verifiers = build_profile_verifiers(["default"], store)
    gateway = build_gateway(
        _gateway_config(), {"work": FakeVaultService()}, token_verifiers=verifiers
    )

    check_gateway_auth_policy("cloud", gateway.profile_servers)  # does not raise
