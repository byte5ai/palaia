"""``create_app`` refuses to mount an unauthenticated gateway in cloud/open mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.app import create_app
from palaia_hub.auth.policy import AuthPolicyError
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.wiring import build_profile_verifiers
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService


def _gateway_config() -> GatewayConfig:
    return GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )


def test_cloud_mode_with_unauthenticated_gateway_refuses_to_start() -> None:
    gateway = build_gateway(_gateway_config(), {"work": FakeVaultService()})

    with pytest.raises(AuthPolicyError, match="default"):
        create_app(HubConfig(mode="cloud", host="127.0.0.1"), gateway=gateway)


def test_cloud_mode_with_authenticated_gateway_starts_fine(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    verifiers = build_profile_verifiers(["default"], store)
    gateway = build_gateway(
        _gateway_config(), {"work": FakeVaultService()}, token_verifiers=verifiers
    )

    app = create_app(HubConfig(mode="cloud", host="127.0.0.1"), gateway=gateway)

    assert app is not None


def test_locked_mode_with_unauthenticated_gateway_starts_fine() -> None:
    gateway = build_gateway(_gateway_config(), {"work": FakeVaultService()})

    app = create_app(HubConfig(mode="locked"), gateway=gateway)

    assert app is not None
