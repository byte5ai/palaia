"""SPEC-210 deliverable #1: :class:`DynamicGateway` rebuild-and-swap.

Complements the subprocess-level e2e test
(``tests/e2e/test_spec210_dynamic_mount.py``) with fast, in-process
coverage of the class's own contract: adding a vault to a fresh profile,
adding a second vault to an *already-mounted* profile (the rebuild-and-swap
path proper), the auth policy re-check, and that an old profile generation
keeps answering a session opened against it after a swap.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.auth.policy import AuthPolicyError
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_add_vault_to_a_brand_new_profile() -> None:
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work", purpose="Work vault."),
        FakeVaultService(),
        profile_paths=["default"],
    )

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_add_vault_to_an_already_mounted_profile_rebuilds_it() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="personal", name="personal", purpose="Personal vault."),
        FakeVaultService(),
        profile_paths=["default"],
    )

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    # Both the vault present since startup and the one added at runtime are
    # reachable through the *same* profile path, rebuilt in place.
    assert "work_memory_search" in names
    assert "personal_memory_search" in names

    await gateway.aclose()


async def test_a_session_opened_before_a_swap_keeps_working_after_it() -> None:
    """The old FastMCP generation for a rebuilt profile is not torn down
    synchronously — a session opened against it keeps answering."""
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work", purpose="Work vault.")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    old_server = gateway.profile_servers["default"]
    async with Client(old_server) as old_client:
        # Trigger the rebuild-and-swap while `old_client`'s session is open
        # against `old_server` specifically (not looked up again by path).
        await gateway.add_vault(
            VaultMountConfig(key="personal", name="personal", purpose="Personal vault."),
            FakeVaultService(),
            profile_paths=["default"],
        )
        # The now-retired generation still answers calls on its own session.
        names = {t.name for t in await old_client.list_tools()}
        assert "work_memory_search" in names
        assert "personal_memory_search" not in names  # old generation never had it

    async with Client(gateway.profile_servers["default"]) as new_client:
        new_names = {t.name for t in await new_client.list_tools()}
    assert "personal_memory_search" in new_names

    await gateway.aclose()


async def test_add_vault_in_cloud_mode_without_a_verifier_raises() -> None:
    gateway = DynamicGateway(GatewayConfig(), {}, mode="cloud")
    await gateway.start()  # no profiles yet — nothing to refuse

    with pytest.raises(AuthPolicyError):
        await gateway.add_vault(
            VaultMountConfig(key="work", name="work"),
            FakeVaultService(),
            profile_paths=["default"],
        )

    await gateway.aclose()


async def test_add_vault_with_a_duplicate_key_raises() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    with pytest.raises(Exception, match="already mounted"):
        await gateway.add_vault(
            VaultMountConfig(key="work", name="work-again"),
            FakeVaultService(),
            profile_paths=["default"],
        )

    await gateway.aclose()
