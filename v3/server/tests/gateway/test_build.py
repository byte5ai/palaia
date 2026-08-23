"""Gateway assembly: profiles, vault disambiguation, renames, config errors.

Covers the SPEC-105 acceptance criteria that don't need a live HTTP
connection: distinguishable tool families for two vaults, a profile
subset hiding the rest, and a rename changing the exposed name after a
config reload (rebuild).
"""

from __future__ import annotations

import logging

import pytest
from fastmcp import Client

from palaia_hub.gateway.build import GatewayConfigError, build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService


def _two_vault_config(**overrides: object) -> GatewayConfig:
    work = VaultMountConfig(key="work", name="work", purpose="Work knowledge.", **overrides)
    personal = VaultMountConfig(key="personal", name="personal", purpose="Personal notes.")
    return GatewayConfig(
        vaults=[work, personal],
        profiles=[
            ProfileConfig(path="full", vaults=["work", "personal"]),
            ProfileConfig(path="work-only", vaults=["work"]),
        ],
    )


async def _tool_names(server: object) -> set[str]:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    return {t.name for t in tools}


@pytest.mark.anyio
async def test_two_vaults_produce_distinguishable_tool_families() -> None:
    config = _two_vault_config()
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}
    gateway = build_gateway(config, services)

    names = await _tool_names(gateway.profile_servers["full"])
    assert "work_memory_search" in names
    assert "personal_memory_search" in names
    assert "work_memory_write" in names
    assert "personal_memory_write" in names


@pytest.mark.anyio
async def test_profile_subset_hides_the_rest() -> None:
    config = _two_vault_config()
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}
    gateway = build_gateway(config, services)

    full_names = await _tool_names(gateway.profile_servers["full"])
    work_only_names = await _tool_names(gateway.profile_servers["work-only"])

    assert "personal_memory_search" in full_names
    assert "personal_memory_search" not in work_only_names
    assert "work_memory_search" in work_only_names


@pytest.mark.anyio
async def test_rename_changes_the_exposed_name_after_reload() -> None:
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}

    before = build_gateway(_two_vault_config(), services)
    before_names = await _tool_names(before.profile_servers["full"])
    assert "work_memory_search" in before_names

    # Simulate a config edit + reload: rebuild with a rename in place.
    after_config = _two_vault_config(tool_renames={"search": "quicksearch"})
    after = build_gateway(after_config, services)
    after_names = await _tool_names(after.profile_servers["full"])

    assert "work_memory_quicksearch" in after_names
    assert "work_memory_search" not in after_names
    # Untouched vault/action is unaffected.
    assert "personal_memory_search" in after_names


@pytest.mark.anyio
async def test_invalid_rename_chars_are_sanitized_with_a_warning(
    caplog: logging.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="palaia_hub.gateway.naming")
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}
    config = _two_vault_config(tool_renames={"search": "quick search!"})

    gateway = build_gateway(config, services)

    names = await _tool_names(gateway.profile_servers["full"])
    assert "work_memory_quick_search" in names
    assert any("sanitized to" in record.message for record in caplog.records)


def test_build_gateway_raises_clear_error_for_missing_vault_service() -> None:
    config = _two_vault_config()
    with pytest.raises(GatewayConfigError, match="personal"):
        build_gateway(config, {"work": FakeVaultService()})


def test_gateway_asgi_mounts_are_keyed_by_profile_path() -> None:
    config = _two_vault_config()
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}
    gateway = build_gateway(config, services)
    assert set(gateway.mounts) == {"/mcp/full", "/mcp/work-only"}


@pytest.mark.anyio
async def test_profile_instructions_carry_every_mounted_vaults_identity() -> None:
    """`mount()` does not propagate a mounted server's `instructions`, so the
    profile server itself must carry an IDENTITY line per vault it exposes
    (deliverable #4) — otherwise a real client connecting to `/mcp/<profile>`
    would see no IDENTITY line at all, only the vault's own (unmounted,
    client-invisible) server ever having one.
    """
    config = _two_vault_config()
    services = {"work": FakeVaultService(), "personal": FakeVaultService()}
    gateway = build_gateway(config, services)

    async with Client(gateway.profile_servers["full"]) as client:
        init = client.initialize_result

    assert init is not None
    assert init.instructions is not None
    assert "IDENTITY: this is the 'work' memory vault" in init.instructions
    assert "IDENTITY: this is the 'personal' memory vault" in init.instructions


def test_zero_profiles_builds_an_empty_but_valid_gateway() -> None:
    config = GatewayConfig(vaults=[VaultMountConfig(key="work", name="work")], profiles=[])
    gateway = build_gateway(config, {"work": FakeVaultService()})
    assert gateway.mounts == {}
