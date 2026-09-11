"""SPEC-210 deliverable #1: :class:`DynamicGateway` rebuild-and-swap.

Complements the subprocess-level e2e test
(``tests/e2e/test_spec210_dynamic_mount.py``) with fast, in-process
coverage of the class's own contract: adding a vault to a fresh profile,
adding a second vault to an *already-mounted* profile (the rebuild-and-swap
path proper), the auth policy re-check, and that an old profile generation
keeps answering a session opened against it after a swap.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastmcp import Client

from palaia_hub.auth.policy import AuthPolicyError
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.wiring import build_profile_verifiers
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.build import GatewayConfigError
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore
from palaia_hub.upstream.models import UpstreamConfig

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
    # Issue #315: refused means *nothing* changed — no unauthenticated
    # profile left serving, no vault or profile recorded in the config.
    assert gateway.profile_servers == {}
    assert gateway.config.profiles == []
    assert gateway.config.vaults == []

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


# ------------------------------------------------------------------ SPEC-301


async def test_upsert_profile_creates_a_brand_new_one() -> None:
    config = GatewayConfig(vaults=[VaultMountConfig(key="work", name="work")])
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    await gateway.upsert_profile("personal", ["work"], label="Personal")

    assert {p.path for p in gateway.config.profiles} == {"personal"}
    assert gateway.config.profiles[0].label == "Personal"
    async with Client(gateway.profile_servers["personal"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_upsert_profile_replaces_an_existing_one_shape() -> None:
    config = GatewayConfig(
        vaults=[
            VaultMountConfig(key="work", name="work"),
            VaultMountConfig(key="personal", name="personal"),
        ],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService(), "personal": FakeVaultService()})
    await gateway.start()

    await gateway.upsert_profile("default", ["work", "personal"], stash=True)

    updated = next(p for p in gateway.config.profiles if p.path == "default")
    assert set(updated.vaults) == {"work", "personal"}
    assert updated.stash is True
    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "personal_memory_search" in names

    await gateway.aclose()


async def test_upsert_profile_with_unknown_vault_raises() -> None:
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    with pytest.raises(GatewayConfigError):
        await gateway.upsert_profile("default", ["nope"])

    await gateway.aclose()


async def test_upsert_profile_in_cloud_mode_without_auth_raises() -> None:
    gateway = DynamicGateway(GatewayConfig(), {}, mode="cloud")
    await gateway.start()

    with pytest.raises(AuthPolicyError):
        await gateway.upsert_profile("default", [])
    assert gateway.profile_servers == {}
    assert gateway.config.profiles == []

    await gateway.aclose()


async def test_semantic_routing_keeps_the_profile_verifier(tmp_path: Path) -> None:
    """Issue #315: switching a profile to semantic routing must not drop its
    token verifier — the router is what gets served."""
    store = TokenStore(home=tmp_path)
    verifiers = build_profile_verifiers(["default"], store)
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(
        config, {"work": FakeVaultService()}, mode="cloud", token_verifiers=verifiers
    )
    await gateway.start()

    await gateway.upsert_profile("default", ["work"], semantic_routing=True)

    server = gateway.profile_servers["default"]
    assert server.auth is verifiers["default"]
    async with Client(server) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {"find_tool", "invoke_tool"}

    await gateway.aclose()


async def test_a_refused_upsert_leaves_the_previous_generation_serving(tmp_path: Path) -> None:
    """Issue #315: a cloud-mode upsert for a path with no verifier is refused
    before anything is mounted or recorded; the existing, authenticated
    profile keeps serving."""
    store = TokenStore(home=tmp_path)
    verifiers = build_profile_verifiers(["default"], store)
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(
        config, {"work": FakeVaultService()}, mode="cloud", token_verifiers=verifiers
    )
    await gateway.start()

    with pytest.raises(AuthPolicyError):
        await gateway.upsert_profile("other", ["work"])

    assert set(gateway.profile_servers) == {"default"}
    assert [p.path for p in gateway.config.profiles] == ["default"]
    assert gateway.profile_servers["default"].auth is verifiers["default"]

    await gateway.aclose()


async def test_remove_profile_unmounts_it() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    await gateway.remove_profile("default")

    assert gateway.config.profiles == []
    assert "default" not in gateway.profile_servers
    router = gateway.asgi_app
    assert not any(getattr(r, "path", None) == "/default" for r in router.routes)  # type: ignore[attr-defined]

    await gateway.aclose()


async def test_remove_profile_leaves_an_in_flight_session_running() -> None:
    """The retiring generation's own already-open session keeps answering —
    same deliberate-leak rule a rebuild's old generation follows."""
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    old_server = gateway.profile_servers["default"]
    async with Client(old_server) as old_client:
        await gateway.remove_profile("default")
        names = {t.name for t in await old_client.list_tools()}
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_remove_profile_unknown_path_raises() -> None:
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    with pytest.raises(KeyError):
        await gateway.remove_profile("nope")

    await gateway.aclose()


async def test_profile_with_stash_true_mounts_the_stash_tools_too() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"], stash=True)],
    )
    stash_service = StashService(StashStore(":memory:"))
    gateway = DynamicGateway(config, {"work": FakeVaultService()}, stash_service=stash_service)
    await gateway.start()

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "stash_set" in names
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_profile_with_stash_false_has_no_stash_tools() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    stash_service = StashService(StashStore(":memory:"))
    gateway = DynamicGateway(config, {"work": FakeVaultService()}, stash_service=stash_service)
    await gateway.start()

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "stash_set" not in names

    await gateway.aclose()


async def test_profile_with_directory_true_mounts_the_directory_tools_too() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"], directory=True)],
    )
    directory_service = DirectoryService(DirectoryStore(":memory:"))
    gateway = DynamicGateway(
        config, {"work": FakeVaultService()}, directory_service=directory_service
    )
    await gateway.start()

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "directory_register" in names
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_profile_with_directory_false_has_no_directory_tools() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    directory_service = DirectoryService(DirectoryStore(":memory:"))
    gateway = DynamicGateway(
        config, {"work": FakeVaultService()}, directory_service=directory_service
    )
    await gateway.start()

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "directory_register" not in names

    await gateway.aclose()


async def test_upsert_profile_with_hidden_tools_hides_them_live() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="default", vaults=["work"])],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    await gateway.upsert_profile("default", ["work"], hidden_tools=["work_memory_delete"])

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "work_memory_delete" not in names
    assert "work_memory_search" in names

    await gateway.aclose()


async def test_upsert_profile_with_semantic_routing_swaps_the_served_surface() -> None:
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work"),
        FakeVaultService(),
        profile_paths=["default"],
    )
    await gateway.upsert_profile("default", ["work"], semantic_routing=True)

    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == {"find_tool", "invoke_tool"}

    await gateway.aclose()


async def test_update_vault_identity_renames_tools_live_across_every_profile() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[
            ProfileConfig(path="default", vaults=["work"]),
            ProfileConfig(path="other", vaults=["work"]),
        ],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()

    await gateway.update_vault_identity(
        VaultMountConfig(key="work", name="work", tool_renames={"search": "find"})
    )

    for path in ("default", "other"):
        async with Client(gateway.profile_servers[path]) as client:
            names = {t.name for t in await client.list_tools()}
        assert "work_memory_find" in names
        assert "work_memory_search" not in names

    await gateway.aclose()


async def test_update_vault_identity_unknown_key_raises() -> None:
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    with pytest.raises(GatewayConfigError):
        await gateway.update_vault_identity(VaultMountConfig(key="ghost", name="ghost"))

    await gateway.aclose()


async def test_set_profile_upstreams_keeps_every_other_profile_field() -> None:
    """Issue #324: connecting an external server to a profile must not reset
    its hidden tools, team flags or routing mode."""
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[
            ProfileConfig(
                path="default",
                label="Desk",
                vaults=["work"],
                stash=True,
                directory=True,
                messenger=True,
                hidden_tools=["work_memory_delete"],
            )
        ],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()})
    await gateway.start()
    await gateway.register_upstream(
        UpstreamConfig(key="fx", kind="http", display_name="Fixture", url="http://127.0.0.1:9/mcp")
    )

    await gateway.set_profile_upstreams("default", ["fx"])

    profile = next(p for p in gateway.config.profiles if p.path == "default")
    assert profile.upstreams == ["fx"]
    assert profile.label == "Desk"
    assert profile.stash and profile.directory and profile.messenger
    assert profile.hidden_tools == ["work_memory_delete"]
    async with Client(gateway.profile_servers["default"]) as client:
        names = {t.name for t in await client.list_tools()}
    assert "work_memory_delete" not in names  # hidden_tools still applied after the change

    await gateway.set_profile_upstreams("default", [])
    profile = next(p for p in gateway.config.profiles if p.path == "default")
    assert profile.upstreams == []
    assert profile.hidden_tools == ["work_memory_delete"]

    with pytest.raises(GatewayConfigError):
        await gateway.set_profile_upstreams("nope", ["fx"])

    await gateway.aclose()
