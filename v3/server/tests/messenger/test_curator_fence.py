"""SPEC-403 deliverable #4, second sentence: **the curator profile gets NO
messenger tools** — the same fail-closed fence SPEC-302 built for external
servers, asserted in the same three independent layers, because the fence
has to hold even if a future change routes around one of them:

1. **Schema.** :class:`ProfileConfig` refuses to *hold* ``messenger: true``
   on the curator path at all — config.yaml, a REST body and a runtime
   rebuild all fail identically.
2. **Builder.** ``_build_profile_server`` refuses even a profile built
   around the schema (``model_construct``, a future code path).
3. **Live gateway.** With the messenger mounted on an ordinary profile, the
   curator profile's own tool surface carries none of it, and calling one of
   its tool names there fails rather than being merely unlisted.

Why the curator specifically: it is an unattended model running over the
operator's own notes (SPEC-206). An outbound message channel there is an
exfiltration path with a delivery guarantee, and an inbound one is a way for
anything holding a handle to feed instructions into a session whose entire
safety argument is that its tool surface is fixed and small.
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
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.build import GatewayConfigError, _build_profile_server, build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.messenger_tools import MESSENGER_TOOL_ACTIONS
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore

pytestmark = pytest.mark.anyio

VAULT = VaultMountConfig(key="work", name="work", purpose="Work vault.")


@pytest.fixture
def messenger() -> MessengerService:
    return MessengerService(
        MessengerStore(":memory:"), DirectoryService(DirectoryStore(":memory:"))
    )


def test_the_schema_refuses_messenger_on_the_curator_profile() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ProfileConfig(path=CURATOR_PROFILE_PATH, vaults=["work"], messenger=True)
    message = str(excinfo.value)
    assert "curator" in message
    assert "messenger" in message


def test_an_ordinary_profile_may_carry_the_messenger() -> None:
    profile = ProfileConfig(path="default", vaults=["work"], messenger=True)
    assert profile.messenger is True


def test_the_builder_refuses_even_a_profile_built_around_the_schema(
    messenger: MessengerService,
) -> None:
    config = GatewayConfig(vaults=[VAULT], profiles=[])
    # `model_construct` skips validators — the only way to express the
    # mistake at all. The builder still refuses.
    sneaky = ProfileConfig.model_construct(
        path=CURATOR_PROFILE_PATH,
        label=None,
        vaults=["work"],
        stash=False,
        directory=False,
        messenger=True,
        hidden_tools=[],
        semantic_routing=False,
        upstreams=[],
    )
    with pytest.raises(GatewayConfigError) as excinfo:
        _build_profile_server(
            sneaky, config, {}, None, (), None, None, None, messenger
        )
    assert "curator" in str(excinfo.value)
    assert "messenger" in str(excinfo.value)


async def test_the_live_curator_profile_carries_no_messenger_tools(
    messenger: MessengerService,
) -> None:
    config = GatewayConfig(
        vaults=[VAULT],
        profiles=[
            ProfileConfig(path="default", vaults=["work"], messenger=True),
            curator_profile(["work"]),
        ],
    )
    gateway = build_gateway(
        config,
        {"work": FakeVaultService()},
        profile_middleware=curator_profile_middleware(
            [VAULT], active_captures=ActiveCaptures()
        ),
        messenger_service=messenger,
    )

    async with Client(gateway.profile_servers["default"]) as client:
        ordinary = {tool.name for tool in await client.list_tools()}
    # The messenger really is mounted on the profile clients connect to.
    assert set(MESSENGER_TOOL_ACTIONS) <= ordinary

    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        curator_tools = {tool.name for tool in await client.list_tools()}
        assert not (set(MESSENGER_TOOL_ACTIONS) & curator_tools)
        assert not any(name.startswith("messenger_") for name in curator_tools)

        # And refused on call, not merely unlisted.
        for name in MESSENGER_TOOL_ACTIONS:
            result = await client.call_tool(name, {}, raise_on_error=False)
            assert result.is_error is True, name


def test_the_curator_action_map_never_learns_a_messenger_tool() -> None:
    """SPEC-206's map is fail-closed: a messenger tool name is not in it, so
    the middleware refuses it as an unknown tool rather than waving it
    through."""
    mapping = curator_tool_actions([VAULT])
    assert not any(name.startswith("messenger_") for name in mapping)
