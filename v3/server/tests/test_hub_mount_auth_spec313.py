"""Issue #313: the hub-wide MCP mounts require a token like any profile.

``/mcp/stash``, ``/mcp/directory``, ``/mcp/messenger``, ``/mcp/hub``,
``/mcp/market`` and ``/mcp/team`` used to be built with no ``auth=`` at all,
in every mode. They now share one verifier that accepts any live ``plt_``
token of this hub (or an OAuth JWT for any of its profiles); what the token
may do there is still decided by its hub-level scopes inside each tool.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

sys.path.insert(0, str(Path(__file__).parent / "auth"))
from _asgi_mcp_client import mcp_client_transport  # noqa: E402

BASE_URL = "https://testserver"
HUB_MOUNTS = ("stash", "directory", "messenger", "hub", "market", "team")


@pytest.mark.anyio
async def test_every_hub_wide_mount_refuses_a_tokenless_client_by_default(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)  # locked, auth_enabled: true — the shipped default
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            for mount in HUB_MOUNTS:
                transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/{mount}/")
                with pytest.raises(Exception, match="401"):
                    async with Client(transport):
                        pass
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


@pytest.mark.anyio
async def test_a_token_bound_to_any_profile_opens_every_hub_wide_mount(tmp_path: Path) -> None:
    """The hub-wide surfaces belong to no profile, so a token for profile
    ``other`` is as good there as one for ``default``."""
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        token = production.token_store.create(
            "t",
            "other",
            ["stash:read", "directory:read", "messenger:read"],
        )
        async with production.app.router.lifespan_context(production.app):
            for mount in HUB_MOUNTS:
                transport = mcp_client_transport(
                    production.app, f"{BASE_URL}/mcp/{mount}/", token=token.token
                )
                async with Client(transport) as client:
                    assert await client.list_tools()
            # A revoked token collapses to the same 401 as no token.
            production.token_store.revoke(token.info.id)
            with pytest.raises(Exception, match="401"):
                async with Client(
                    mcp_client_transport(production.app, f"{BASE_URL}/mcp/hub/", token=token.token)
                ):
                    pass
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


@pytest.mark.anyio
async def test_hub_level_scopes_are_enforced_on_the_hub_wide_mounts(tmp_path: Path) -> None:
    """Passing the door is not the same as being allowed through it: a token
    without ``stash:write`` connects to ``/mcp/stash`` but ``stash_set`` is
    refused with the missing-scope error."""
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        read_only = production.token_store.create("ro", "default", ["stash:read"])
        async with production.app.router.lifespan_context(production.app):
            transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/stash/", token=read_only.token
            )
            async with Client(transport) as client:
                result = await client.call_tool(
                    "stash_set",
                    {"namespace": "ns", "key": "k", "value": "v"},
                    raise_on_error=False,
                )
        assert result.is_error
        text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
        assert "stash:write" in text
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


@pytest.mark.anyio
async def test_auth_off_in_locked_mode_keeps_the_hub_wide_mounts_open(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("mode: locked\nauth_enabled: false\n", encoding="utf-8")
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/stash/")
            async with Client(transport) as client:
                assert await client.list_tools()
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


def _close(production: object) -> None:
    for attribute in ("stash_store", "directory_store", "messenger_store"):
        store = getattr(production, attribute)
        if store is not None:
            store.close()
