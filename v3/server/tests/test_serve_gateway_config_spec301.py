"""SPEC-301: ``build_production_app`` actually builds the gateway from
``config.yaml``'s ``gateway:`` section — vault identity overrides
(including tool renames, sanitized per SPEC-105) and custom profiles — and
a profile created at runtime through the REST editor survives a restart
(persisted, then re-resolved from the same file)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

BASE_URL = "https://testserver"


async def _registered_vault(home: Path, key: str) -> None:
    registry = VaultRegistry(home)
    await registry.create(key, home / "vaults" / key, purpose=f"{key} vault.")


@pytest.mark.anyio
async def test_configured_tool_rename_is_applied_and_sanitized(tmp_path: Path) -> None:
    await _registered_vault(tmp_path, "work")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  vaults:\n"
        "    - key: work\n"
        "      tool_renames:\n"
        "        search: find!!\n"  # invalid chars — must be sanitized, not rejected
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)

    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            async with Client(production.dynamic_gateway.profile_servers["default"]) as client:
                names = {t.name for t in await client.list_tools()}
    finally:
        await production.dynamic_gateway.aclose()
        assert production.stash_store is not None
        production.stash_store.close()
        for index in production.indexes.values():
            await index.close()

    # Sanitized (SPEC-105: invalid chars stripped, not a hard error) rather
    # than the plain `work_memory_search`.
    assert "work_memory_find" in names
    assert "work_memory_search" not in names


@pytest.mark.anyio
async def test_a_profile_created_via_rest_survives_a_restart(tmp_path: Path) -> None:
    await _registered_vault(tmp_path, "work")
    config = load_config(home=tmp_path)  # zero-config: writes the default template

    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production.app), base_url=BASE_URL
            ) as http:
                response = await http.post(
                    "/api/gateway/profiles", json={"path": "personal", "vaults": ["work"]}
                )
                assert response.status_code == 200
    finally:
        await production.dynamic_gateway.aclose()
        assert production.stash_store is not None
        production.stash_store.close()
        for index in production.indexes.values():
            await index.close()

    # "Restart": reload config from the same file, rebuild the app fresh.
    restarted_config = load_config(home=tmp_path, create_if_missing=False)
    assert restarted_config.gateway is not None
    assert any(p.path == "personal" for p in restarted_config.gateway.profiles)

    restarted = await build_production_app(restarted_config, home=tmp_path)
    try:
        async with restarted.app.router.lifespan_context(restarted.app):
            assert "personal" in restarted.dynamic_gateway.profile_servers
            async with Client(restarted.dynamic_gateway.profile_servers["personal"]) as client:
                names = {t.name for t in await client.list_tools()}
            assert "work_memory_search" in names
    finally:
        await restarted.dynamic_gateway.aclose()
        assert restarted.stash_store is not None
        restarted.stash_store.close()
        for index in restarted.indexes.values():
            await index.close()
