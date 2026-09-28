"""``memory_status`` on every memory profile (issue #524).

Agents called their memory "unavailable" from start-up notices or tool names
they did not find. One cheap, un-namespaced call on the profile they are
already connected to lets them check instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.server.auth import AccessToken

from palaia_hub import __version__
from palaia_hub.gateway import status_tool
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.vault_protocol import NoteRecord
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import EventBus, VaultEngine

pytestmark = pytest.mark.anyio


def _config() -> GatewayConfig:
    return GatewayConfig(
        vaults=[
            VaultMountConfig(key="work", name="work", purpose="Work knowledge."),
            VaultMountConfig(key="family", name="family", purpose="Family plans."),
        ],
        profiles=[ProfileConfig(path="default", vaults=["work", "family"])],
    )


def _services() -> dict[str, FakeVaultService]:
    work = FakeVaultService()
    for slug in ("a", "b"):
        work.seed(NoteRecord(permalink=f"notes/{slug}", title=slug.upper(), body="x"))
    return {"work": work, "family": FakeVaultService()}


async def _call(server: object) -> Any:  # noqa: ANN001
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        result = await client.call_tool("memory_status", {})
    return names, result


async def test_the_profile_lists_each_memory_with_access_and_tool_prefix() -> None:
    gateway = build_gateway(_config(), _services())

    names, result = await _call(gateway.profile_servers["default"])

    assert "memory_status" in names
    data = result.structured_content
    assert data["hub_version"] == __version__
    assert data["profile"] == "default"
    assert data["client"] is None
    work, family = data["memories"]
    assert work["memory"] == "work"
    assert work["tool_prefix"] == "work_memory_"
    assert (work["read"], work["write"]) == (True, True)
    assert work["notes"] == 2
    assert work["search"] == "fulltext"
    assert family["notes"] == 0
    text = result.content[0].text
    assert "the connection works" in text
    assert "tools start with work_memory_" in text


async def test_access_follows_the_tokens_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    token = AccessToken(
        token="t",
        client_id="abc",
        scopes=["vault:work:read"],
        subject="Claude Code",
    )
    monkeypatch.setattr(status_tool, "get_access_token", lambda: token)
    gateway = build_gateway(_config(), _services())

    _, result = await _call(gateway.profile_servers["default"])

    data = result.structured_content
    assert data["client"] == "Claude Code"
    work, family = data["memories"]
    assert (work["read"], work["write"]) == (True, False)
    assert (family["read"], family["write"]) == (False, False)
    assert "work: read only" in result.content[0].text
    assert "family: no access" in result.content[0].text


async def test_a_profile_without_memories_has_no_status_tool() -> None:
    config = GatewayConfig(
        vaults=[VaultMountConfig(key="work", name="work")],
        profiles=[ProfileConfig(path="empty", vaults=[])],
    )
    gateway = build_gateway(config, {"work": FakeVaultService()})
    async with Client(gateway.profile_servers["empty"]) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert "memory_status" not in names


async def _engine(tmp_path: Path) -> VaultEngine:
    engine = VaultEngine(tmp_path / "work", "work", bus=EventBus())
    await engine.open(purpose="status test", create=True)
    return engine


async def test_a_real_vault_without_an_index_reports_full_text_search(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    try:
        status = await EngineVaultService(engine).status()
    finally:
        await engine.close()
    assert status.search == "fulltext"
    assert "no search index" in status.search_note
    # The manifest under meta/ is not counted as content.
    assert status.notes == 0


async def test_a_real_vault_with_embeddings_off_says_so(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open(start_worker=False)
    try:
        status = await EngineVaultService(engine, index).status()
    finally:
        await index.close()
        await engine.close()
    assert status.search == "fulltext"
    assert status.search_note == "embeddings are switched off"
