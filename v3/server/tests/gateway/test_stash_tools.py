"""Tool-ergonomics + IDENTITY acceptance tests for the stash tool family
(SPEC-202) — same treatment as ``test_memory_tools.py`` gives the memory
family: annotations-lint, alias absorption, dual text/json output, and an
IDENTITY line that distinguishes stash from memory.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.gateway.stash_tools import STASH_TOOL_ACTIONS, build_stash_server
from palaia_hub.stash.service import StashService
from palaia_hub.stash.store import StashStore


@pytest.fixture
def service() -> StashService:
    return StashService(StashStore(":memory:"))


@pytest.fixture
def server(service: StashService):  # noqa: ANN201 - fastmcp.FastMCP, imported lazily
    return build_stash_server(service)


@pytest.mark.anyio
async def test_every_action_is_exposed_as_a_tool(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == set(STASH_TOOL_ACTIONS)


@pytest.mark.anyio
async def test_annotations_lint_every_tool_has_readonly_and_destructive_hints(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
    assert tools
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.readOnlyHint is not None, f"{tool.name} missing readOnlyHint"
        assert tool.annotations.destructiveHint is not None, f"{tool.name} missing destructiveHint"


@pytest.mark.anyio
async def test_write_tools_are_not_readonly(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("stash_set", "stash_del"):
        assert tools[name].annotations.readOnlyHint is False


@pytest.mark.anyio
async def test_read_tools_are_readonly(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("stash_get", "stash_list", "stash_status"):
        assert tools[name].annotations.readOnlyHint is True


@pytest.mark.anyio
async def test_stash_set_accepts_canonical_params_and_round_trips(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool(
            "stash_set", {"namespace": "jobs", "key": "job-1", "value": {"a": 1}}
        )
        assert result.structured_content is not None
        get_result = await client.call_tool("stash_get", {"namespace": "jobs", "key": "job-1"})
    assert get_result.structured_content["found"] is True
    assert get_result.structured_content["entry"]["value"] == {"a": 1}
    assert isinstance(result.content[0].text, str) and result.content[0].text  # dual output


@pytest.mark.anyio
async def test_alias_absorption_ns_name_and_data(server) -> None:  # noqa: ANN001
    """`namespace`/`key`/`value` also accept `ns`/`name`/`data` — the
    published schema still only shows the canonical names."""
    async with Client(server) as client:
        set_result = await client.call_tool(
            "stash_set", {"ns": "jobs", "name": "job-2", "data": "hello"}
        )
        assert not set_result.is_error
        get_result = await client.call_tool("stash_get", {"ns": "jobs", "name": "job-2"})
    assert get_result.structured_content["entry"]["value"] == "hello"


@pytest.mark.anyio
async def test_published_schema_shows_only_canonical_param_names(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    props = tools["stash_set"].inputSchema["properties"]
    assert set(props) == {"namespace", "key", "value", "ttl_seconds", "stale_after_seconds"}


@pytest.mark.anyio
async def test_server_instructions_carry_identity_and_distinguish_from_memory(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        init = client.initialize_result
    assert init is not None
    assert init.instructions is not None
    assert init.instructions.startswith("IDENTITY:")
    assert "NOT memory" in init.instructions
    assert "memory tools" in init.instructions


@pytest.mark.anyio
async def test_every_tool_description_mentions_the_identity_distinction(
    server,  # noqa: ANN001
) -> None:
    """Acceptance criterion: 'tool descriptions distinguish stash from
    memory' — checked per-tool, not just on the server instructions, since
    a client's tool picker often shows only the tool description."""
    async with Client(server) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description is not None
        assert "NOT memory" in tool.description


@pytest.mark.anyio
async def test_del_and_status_round_trip(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await client.call_tool("stash_set", {"namespace": "jobs", "key": "a", "value": 1})
        status = await client.call_tool("stash_status", {})
        assert status.structured_content["total_entries"] == 1
        deleted = await client.call_tool("stash_del", {"namespace": "jobs", "key": "a"})
        assert deleted.structured_content["deleted"] is True
        listing = await client.call_tool("stash_list", {"namespace": "jobs"})
        assert listing.structured_content["entries"] == []
