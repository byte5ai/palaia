"""The curator profile never gets Telegram tools — on the **live** gateway
too (issue #411's fence, issue #439's wiring).

``tests/messenger/test_curator_fence.py`` proves the messenger's version of
this fence against the static :func:`~palaia_hub.gateway.build.build_gateway`.
Issue #439 hands the Telegram service to
:class:`~palaia_hub.gateway.dynamic.DynamicGateway`, which rebuilds profiles
at runtime — so the fence is asserted here where it now actually has to
hold: with the service present, through a start *and* a rebuild, and against
a runtime edit that tries to turn the flag on.
"""

from __future__ import annotations

import pytest
from fastmcp import Client
from pydantic import ValidationError

from palaia_hub.curator.policy import ActiveCaptures
from palaia_hub.curator.profile import (
    CURATOR_PROFILE_PATH,
    curator_profile,
    curator_profile_middleware,
    curator_tool_actions,
)
from palaia_hub.gateway.build import GatewayConfigError, _build_profile_server
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.telegram_tools import TELEGRAM_TOOL_ACTIONS
from palaia_hub.telegram.service import TelegramService

pytestmark = pytest.mark.anyio

VAULT = VaultMountConfig(key="work", name="work", purpose="Work vault.")


def _live_gateway(service: TelegramService) -> DynamicGateway:
    return DynamicGateway(
        GatewayConfig(
            vaults=[VAULT],
            profiles=[
                ProfileConfig(path="default", vaults=["work"], telegram=True),
                curator_profile(["work"]),
            ],
        ),
        {"work": FakeVaultService()},
        profile_middleware=curator_profile_middleware([VAULT], active_captures=ActiveCaptures()),
        telegram_service=service,
    )


async def _names(gateway: DynamicGateway, path: str) -> set[str]:
    async with Client(gateway.profile_servers[path]) as client:
        return {tool.name for tool in await client.list_tools()}


async def test_the_live_curator_profile_carries_no_telegram_tools(
    service: TelegramService,
) -> None:
    gateway = _live_gateway(service)
    await gateway.start()
    try:
        # The service really is mounted on the profile clients connect to.
        assert set(TELEGRAM_TOOL_ACTIONS) <= await _names(gateway, "default")

        curator_tools = await _names(gateway, CURATOR_PROFILE_PATH)
        assert not (set(TELEGRAM_TOOL_ACTIONS) & curator_tools)
        assert not any(name.startswith("telegram_") for name in curator_tools)

        # Refused on call, not merely unlisted.
        async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
            for name in TELEGRAM_TOOL_ACTIONS:
                result = await client.call_tool(name, {}, raise_on_error=False)
                assert result.is_error is True, name
    finally:
        await gateway.aclose()


async def test_a_curator_rebuild_still_carries_no_telegram_tools(
    service: TelegramService,
) -> None:
    """A vault added at runtime rebuilds the curator profile — with the
    service in hand this time, which is exactly when the fence matters."""
    gateway = _live_gateway(service)
    await gateway.start()
    try:
        before = gateway.profile_servers[CURATOR_PROFILE_PATH]
        await gateway.add_vault(
            VaultMountConfig(key="notes", name="notes"),
            FakeVaultService(),
            profile_paths=["default", CURATOR_PROFILE_PATH],
        )
        # The rebuild happened: a new server, over the new vault set.
        assert gateway.profile_servers[CURATOR_PROFILE_PATH] is not before
        curator = next(p for p in gateway.config.profiles if p.path == CURATOR_PROFILE_PATH)
        assert curator.vaults == ["work", "notes"]
        curator_tools = await _names(gateway, CURATOR_PROFILE_PATH)
        assert not any(name.startswith("telegram_") for name in curator_tools)
        assert set(TELEGRAM_TOOL_ACTIONS) <= await _names(gateway, "default")
    finally:
        await gateway.aclose()


async def test_a_runtime_edit_cannot_put_telegram_on_the_curator(
    service: TelegramService,
) -> None:
    gateway = _live_gateway(service)
    await gateway.start()
    try:
        with pytest.raises(ValidationError, match="curator"):
            await gateway.upsert_profile(CURATOR_PROFILE_PATH, ["work"], telegram=True)
        assert not any(
            name.startswith("telegram_") for name in await _names(gateway, CURATOR_PROFILE_PATH)
        )
    finally:
        await gateway.aclose()


def test_the_builder_refuses_even_a_profile_built_around_the_schema(
    service: TelegramService,
) -> None:
    config = GatewayConfig(vaults=[VAULT], profiles=[])
    sneaky = ProfileConfig.model_construct(
        path=CURATOR_PROFILE_PATH,
        label=None,
        vaults=["work"],
        stash=False,
        directory=False,
        messenger=False,
        telegram=True,
        hidden_tools=[],
        semantic_routing=False,
        upstreams=[],
    )
    with pytest.raises(GatewayConfigError, match="Telegram"):
        _build_profile_server(sneaky, config, {}, None, telegram_service=service)


def test_the_curator_action_map_never_learns_a_telegram_tool() -> None:
    assert not any(name.startswith("telegram_") for name in curator_tool_actions([VAULT]))
