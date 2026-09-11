"""SPEC-402: ``build_production_app`` wires one hub-wide session directory,
shared by the ``/mcp/directory`` tool family and any profile with
``directory: true`` — same "flag ahead of the service" wiring
``test_serve_stash_spec301.py`` established for stash."""

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
async def test_hub_wide_directory_is_mounted(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            # Issue #313: the hub-wide mount needs a token like any profile.
            with pytest.raises(Exception):  # noqa: B017 - fastmcp surfaces the 401 as a transport error
                async with Client(
                    mcp_client_transport(production.app, f"{BASE_URL}/mcp/directory/")
                ):
                    pass
            token = production.token_store.create(
                "t", "default", ["directory:read", "directory:write"]
            )
            transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/directory/", token=token.token
            )
            async with Client(transport) as client:
                names = {t.name for t in await client.list_tools()}
        assert "directory_register" in names
    finally:
        await production.dynamic_gateway.aclose()
        assert production.directory_store is not None
        production.directory_store.close()


@pytest.mark.anyio
async def test_profile_with_directory_true_shares_the_hub_wide_directory(
    tmp_path: Path,
) -> None:
    await _registered_vault(tmp_path, "work")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      directory: true\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            # Register through the profile-mounted copy, read through the
            # hub-wide `/mcp/directory` mount — same store, so it round-trips.
            profile_transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/default/")
            async with Client(profile_transport) as profile_client:
                registered = await profile_client.call_tool(
                    "directory_register", {"scope": "shared session"}
                )
            handle = registered.structured_content["session"]["handle"]

            directory_transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/directory/")
            async with Client(directory_transport) as directory_client:
                listing = await directory_client.call_tool("directory_list", {})
        handles = {s["handle"] for s in listing.structured_content["sessions"]}
        assert handle in handles
    finally:
        await production.dynamic_gateway.aclose()
        assert production.directory_store is not None
        production.directory_store.close()
        for index in production.indexes.values():
            await index.close()
