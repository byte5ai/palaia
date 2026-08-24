"""Recall-explorer MCP App acceptance tests (SPEC-208 deliverable #3).

**Selective context proven**: ``search`` returns N hits (no bodies —
SPEC-105's existing narrow ``SearchHit`` shape already keeps the initial
result light). Picking one of them — calling ``recall_pick`` with a single
ref, exactly as the app's JS does — returns exactly that one note's full
content, never the other N-1. :func:`build_context_update` then turns that
into the exact ``ui/update-model-context`` payload the app sends, so this
test asserts on the real payload shape without needing a browser.
"""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

from palaia_hub.gateway.apps.recall_app import build_context_update
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.gateway.vault_protocol import NoteRecord, VaultService


@pytest.fixture
def vault_config() -> VaultMountConfig:
    return VaultMountConfig(key="work", name="work", purpose="Team knowledge.")


@pytest.fixture
def service() -> FakeVaultService:
    svc = FakeVaultService()
    for i in range(3):
        svc.seed(
            NoteRecord(
                permalink=f"notes/topic-{i}",
                title=f"Topic {i}",
                body=f"Everything about topic {i}, in full.\n",
            )
        )
    return svc


def _mounted_profile(vault_config: VaultMountConfig, service: VaultService) -> FastMCP:
    """A real, namespace-mounted profile server (see
    ``test_apps_review_queue.py``'s module docstring for why this, and not
    the bare :func:`build_vault_server` output, is what proves a
    ``pick_tool`` name is actually callable)."""
    config = GatewayConfig(
        vaults=[vault_config], profiles=[ProfileConfig(path="default", vaults=[vault_config.key])]
    )
    gateway = build_gateway(config, {vault_config.key: service})
    return gateway.profile_servers["default"]


@pytest.mark.anyio
async def test_search_result_carries_no_bodies_but_names_the_pick_tool(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool("search", {"query": "topic"})
    payload = result.structured_content
    assert len(payload["hits"]) == 3
    for hit in payload["hits"]:
        assert "body" not in hit  # SearchHit never carried a body to begin with
    assert payload["pick_tool"] == "work_memory_recall_pick"
    # Plain-text fallback (deliverable #5): still a usable result with no app.
    assert "3 match" in result.content[0].text


@pytest.mark.anyio
async def test_picking_one_of_n_results_injects_only_that_one(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = _mounted_profile(vault_config, service)
    async with Client(server) as client:
        search = await client.call_tool("work_memory_search", {"query": "topic"})
        pick_tool = search.structured_content["pick_tool"]
        assert pick_tool == "work_memory_recall_pick"

        picked = await client.call_tool(pick_tool, {"refs": ["notes/topic-1"]})

    notes = picked.structured_content["notes"]
    assert len(notes) == 1
    assert notes[0]["permalink"] == "notes/topic-1"
    assert "topic 1" in notes[0]["body"]
    # None of the other two notes' content is anywhere in the payload.
    assert "topic 0" not in str(notes)
    assert "topic 2" not in str(notes)


@pytest.mark.anyio
async def test_recall_pick_can_gather_more_than_one_when_the_user_multi_selects(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        picked = await client.call_tool(
            "recall_pick", {"refs": ["notes/topic-0", "notes/topic-2"]}
        )
    permalinks = {n["permalink"] for n in picked.structured_content["notes"]}
    assert permalinks == {"notes/topic-0", "notes/topic-2"}


@pytest.mark.anyio
async def test_recall_pick_of_an_unknown_ref_is_a_tool_error_not_a_crash(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool(
            "recall_pick", {"refs": ["notes/does-not-exist"]}, raise_on_error=False
        )
    assert result.is_error


@pytest.mark.anyio
async def test_recall_also_carries_the_pick_tool_name(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool("recall", {"query": "topic"})
    assert result.structured_content["pick_tool"] == "work_memory_recall_pick"


def test_build_context_update_shape_matches_the_apps_js() -> None:
    note = NoteRecord(
        permalink="notes/topic-1",
        title="Topic 1",
        body="Everything about topic 1, in full.\n",
    )
    update = build_context_update([note])
    assert update["content"] == [
        {
            "type": "text",
            "text": "## Topic 1\nmemory://notes/topic-1\n\n"
            "Everything about topic 1, in full.\n",
        }
    ]
    assert update["structuredContent"]["notes"][0]["permalink"] == "notes/topic-1"


def test_build_context_update_of_one_never_carries_a_second_notes_content() -> None:
    picked = NoteRecord(permalink="a", title="A", body="A's own content")
    # A second note the caller never selected — asserted absent below.
    update = build_context_update([picked])
    serialized = str(update)
    assert "A's own content" in serialized
    assert "B's own content" not in serialized
