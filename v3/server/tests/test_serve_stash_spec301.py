"""SPEC-301: ``build_production_app`` wires one hub-wide stash, shared by
the ``/mcp/stash`` tool family and any profile with ``stash: true`` —
closing a pre-existing gap where production never wired a stash service at
all (SPEC-202 built the tool family; nothing before this SPEC ever
constructed one in ``build_production_app``)."""

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


async def _registered_vault(home: Path, key: str) -> None:
    registry = VaultRegistry(home)
    await registry.create(key, home / "vaults" / key, purpose=f"{key} vault.")


@pytest.mark.anyio
async def test_hub_wide_stash_is_mounted(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            # Issue #313: `auth_enabled: true` (the default) covers the
            # hub-wide mounts too — no token, no tools.
            with pytest.raises(Exception):  # noqa: B017 - fastmcp surfaces the 401 as a transport error
                async with Client(mcp_client_transport(production.app, f"{BASE_URL}/mcp/stash/")):
                    pass
            token = production.token_store.create("t", "default", ["stash:read", "stash:write"])
            transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/stash/", token=token.token
            )
            async with Client(transport) as client:
                names = {t.name for t in await client.list_tools()}
        assert "stash_set" in names
    finally:
        await production.dynamic_gateway.aclose()
        assert production.stash_store is not None
        production.stash_store.close()


@pytest.mark.anyio
async def test_profile_with_stash_true_shares_the_hub_wide_stash(tmp_path: Path) -> None:
    await _registered_vault(tmp_path, "work")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      stash: true\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            # Set through the profile-mounted copy, read through the
            # hub-wide `/mcp/stash` mount — same store, so the value
            # round-trips.
            profile_transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/default/")
            async with Client(profile_transport) as profile_client:
                await profile_client.call_tool(
                    "stash_set", {"namespace": "ns", "key": "k", "value": "v"}
                )

            stash_transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/stash/")
            async with Client(stash_transport) as stash_client:
                result = await stash_client.call_tool("stash_get", {"namespace": "ns", "key": "k"})
        assert not result.is_error
        text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
        assert "v" in text
    finally:
        await production.dynamic_gateway.aclose()
        assert production.stash_store is not None
        production.stash_store.close()
        for index in production.indexes.values():
            await index.close()
