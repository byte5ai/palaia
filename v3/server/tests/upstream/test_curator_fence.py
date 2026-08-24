"""SPEC-302 acceptance criterion #5 / deliverable #6: the curator profile
provably cannot see or call an external server's tools.

Three independent layers, each asserted on its own, because the fence has to
hold even if a future change routes around one of them:

1. **Schema.** :class:`ProfileConfig` refuses to *hold* upstreams on the
   curator path at all — a config.yaml, a REST body and a runtime rebuild all
   fail identically.
2. **Builder.** ``_build_profile_server`` refuses even if a caller
   constructed the profile some other way (``model_construct``, a future
   code path).
3. **Live gateway.** With an upstream up and mounted on an ordinary profile,
   the curator profile's own tool surface carries none of it, and calling one
   of its tool names there fails — which is also the fail-closed behavior
   SPEC-206's middleware map already guarantees for an unmapped name.
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
from palaia_hub.upstream.models import UpstreamConfig
from palaia_hub.upstream.service import UpstreamService

from .conftest import HttpUpstream

pytestmark = pytest.mark.anyio

VAULT = VaultMountConfig(key="work", name="work", purpose="Work vault.")


def _upstream(url: str) -> UpstreamConfig:
    return UpstreamConfig(
        key="fixture", kind="http", display_name="Fixture server", url=url
    )


def test_the_schema_refuses_upstreams_on_the_curator_profile() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ProfileConfig(path=CURATOR_PROFILE_PATH, vaults=["work"], upstreams=["fixture"])
    assert "curator" in str(excinfo.value)


def test_the_builder_refuses_even_a_profile_built_around_the_schema() -> None:
    upstream = _upstream("http://127.0.0.1:9/mcp/")
    config = GatewayConfig(vaults=[VAULT], profiles=[], upstreams=[upstream])
    # `model_construct` skips validators — the only way to express the
    # mistake at all. The builder still refuses.
    sneaky = ProfileConfig.model_construct(
        path=CURATOR_PROFILE_PATH,
        label=None,
        vaults=["work"],
        stash=False,
        upstreams=["fixture"],
    )
    with pytest.raises(GatewayConfigError) as excinfo:
        _build_profile_server(sneaky, config, {}, None)
    assert "curator" in str(excinfo.value)


async def test_the_live_curator_profile_carries_no_upstream_tools(
    http_upstream: HttpUpstream,
) -> None:
    upstream = _upstream(http_upstream.url)
    service = UpstreamService([upstream])
    config = GatewayConfig(
        vaults=[VAULT],
        profiles=[
            ProfileConfig(path="default", vaults=["work"], upstreams=["fixture"]),
            curator_profile(["work"]),
        ],
        upstreams=[upstream],
    )
    gateway = DynamicGateway(
        config,
        {"work": FakeVaultService()},
        upstream_service=service,
        profile_middleware=curator_profile_middleware(
            [VAULT], active_captures=ActiveCaptures()
        ),
    )
    await gateway.start()
    await service.probe_all()
    await gateway.refresh_upstreams()
    try:
        async with Client(gateway.profile_servers["default"]) as client:
            ordinary = {tool.name for tool in await client.list_tools()}
        assert "fixture_echo" in ordinary  # it really is connected and up

        async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
            curator_tools = {tool.name for tool in await client.list_tools()}
            assert not any(name.startswith("fixture_") for name in curator_tools)

            # And it is refused on call, not merely unlisted.
            result = await client.call_tool(
                "fixture_echo", {"text": "should never happen"}, raise_on_error=False
            )
        assert result.is_error is True
    finally:
        await gateway.aclose()
        await service.aclose()


def test_the_curator_action_map_never_learns_an_upstream_tool() -> None:
    """SPEC-206's map is fail-closed: an upstream tool name is not in it, so
    the middleware refuses it with "unknown tool" rather than waving it
    through."""
    mapping = curator_tool_actions([VAULT])
    assert not any(name.startswith("fixture_") for name in mapping)


async def test_refresh_upstreams_never_rebuilds_the_curator_profile(
    http_upstream: HttpUpstream,
) -> None:
    upstream = _upstream(http_upstream.url)
    service = UpstreamService([upstream])
    config = GatewayConfig(
        vaults=[VAULT],
        profiles=[
            ProfileConfig(path="default", vaults=["work"], upstreams=["fixture"]),
            curator_profile(["work"]),
        ],
        upstreams=[upstream],
    )
    gateway = DynamicGateway(config, {"work": FakeVaultService()}, upstream_service=service)
    await gateway.start()
    try:
        await service.probe_all()
        assert await gateway.refresh_upstreams() == ["default"]
    finally:
        await gateway.aclose()
        await service.aclose()
