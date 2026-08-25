"""Tool-ergonomics + acceptance tests for the session directory tool family
(SPEC-402) — same treatment as ``test_stash_tools.py`` gives stash:
annotations-lint, alias absorption, dual text/json output, an IDENTITY line
distinguishing it from memory/stash, plus the SPEC's own register/heartbeat/
impersonation/scope acceptance criteria driven through a real
``fastmcp.Client``.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.directory_tools import DIRECTORY_TOOL_ACTIONS, build_directory_server


@pytest.fixture
def service() -> DirectoryService:
    return DirectoryService(DirectoryStore(":memory:"))


@pytest.fixture
def server(service: DirectoryService):  # noqa: ANN201 - fastmcp.FastMCP, imported lazily
    return build_directory_server(service)


@pytest.mark.anyio
async def test_every_action_is_exposed_as_a_tool(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == set(DIRECTORY_TOOL_ACTIONS)


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
    write_tools = (
        "directory_register",
        "directory_heartbeat",
        "directory_update",
        "directory_deregister",
    )
    for name in write_tools:
        assert tools[name].annotations.readOnlyHint is False


@pytest.mark.anyio
async def test_read_tools_are_readonly(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("directory_list", "directory_query"):
        assert tools[name].annotations.readOnlyHint is True


@pytest.mark.anyio
async def test_server_instructions_carry_identity_and_distinguish_from_memory_and_stash(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        init = client.initialize_result
    assert init is not None
    assert init.instructions is not None
    assert init.instructions.startswith("IDENTITY:")
    assert "NOT memory and NOT the stash" in init.instructions


@pytest.mark.anyio
async def test_every_tool_description_mentions_the_identity_distinction(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description is not None
        assert "NOT memory and NOT the stash" in tool.description


@pytest.mark.anyio
async def test_published_schema_shows_only_canonical_param_names(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    props = tools["directory_register"].inputSchema["properties"]
    assert set(props) == {
        "scope",
        "host",
        "platform",
        "agent_kind",
        "model",
        "capabilities",
        "ttl_seconds",
    }


@pytest.mark.anyio
async def test_alias_absorption_client_and_kind(server) -> None:  # noqa: ANN001
    """`platform`/`agent_kind` also accept `client`/`kind` — the published
    schema still only shows the canonical names."""
    async with Client(server) as client:
        result = await client.call_tool(
            "directory_register", {"client": "claude-code", "kind": "coder"}
        )
        assert not result.is_error
        listing = await client.call_tool("directory_list", {})
    session = listing.structured_content["sessions"][0]
    assert session["platform"] == "claude-code"
    assert session["agent_kind"] == "coder"


# -- register -> list round-trip; handle stability across heartbeats --------


@pytest.mark.anyio
async def test_register_then_list_round_trips(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        register_result = await client.call_tool(
            "directory_register", {"scope": "refactoring billing", "platform": "claude-code"}
        )
        assert not register_result.is_error
        handle = register_result.structured_content["session"]["handle"]
        secret = register_result.structured_content["session_secret"]
        assert handle and secret

        listing = await client.call_tool("directory_list", {})
    sessions = listing.structured_content["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["handle"] == handle
    assert "session_secret" not in sessions[0]


@pytest.mark.anyio
async def test_handle_is_stable_across_heartbeats(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        registered = await client.call_tool("directory_register", {"scope": "a"})
        handle = registered.structured_content["session"]["handle"]
        secret = registered.structured_content["session_secret"]

        heartbeat_1 = await client.call_tool(
            "directory_heartbeat", {"handle": handle, "session_secret": secret}
        )
        heartbeat_2 = await client.call_tool(
            "directory_heartbeat", {"handle": handle, "session_secret": secret}
        )
    assert heartbeat_1.structured_content["session"]["handle"] == handle
    assert heartbeat_2.structured_content["session"]["handle"] == handle


# -- impersonation guard ------------------------------------------------------


@pytest.mark.anyio
async def test_wrong_session_secret_cannot_heartbeat_another_session(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        a = await client.call_tool("directory_register", {"scope": "a"})
        b = await client.call_tool("directory_register", {"scope": "b"})
        a_handle = a.structured_content["session"]["handle"]
        b_secret = b.structured_content["session_secret"]

        result = await client.call_tool(
            "directory_heartbeat",
            {"handle": a_handle, "session_secret": b_secret},
            raise_on_error=False,
        )
    assert result.is_error


@pytest.mark.anyio
async def test_wrong_session_secret_cannot_update_another_session(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        a = await client.call_tool("directory_register", {"scope": "a"})
        b = await client.call_tool("directory_register", {"scope": "b"})
        a_handle = a.structured_content["session"]["handle"]
        b_secret = b.structured_content["session_secret"]

        result = await client.call_tool(
            "directory_update",
            {"handle": a_handle, "session_secret": b_secret, "scope": "hijacked"},
            raise_on_error=False,
        )
    assert result.is_error


@pytest.mark.anyio
async def test_wrong_session_secret_cannot_deregister_another_session(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        a = await client.call_tool("directory_register", {"scope": "a"})
        b = await client.call_tool("directory_register", {"scope": "b"})
        a_handle = a.structured_content["session"]["handle"]
        b_secret = b.structured_content["session_secret"]

        result = await client.call_tool(
            "directory_deregister",
            {"handle": a_handle, "session_secret": b_secret},
            raise_on_error=False,
        )
        assert result.is_error

        # `a` is still there — the deregister attempt did not go through.
        listing = await client.call_tool("directory_list", {})
    handles = {s["handle"] for s in listing.structured_content["sessions"]}
    assert a_handle in handles


# -- query -------------------------------------------------------------------


@pytest.mark.anyio
async def test_query_by_scope_substring_and_capability(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await client.call_tool(
            "directory_register",
            {"scope": "refactoring the billing service", "capabilities": ["review"]},
        )
        await client.call_tool("directory_register", {"scope": "writing docs"})

        by_scope = await client.call_tool("directory_query", {"scope_contains": "billing"})
        by_capability = await client.call_tool("directory_query", {"capability": "review"})

    assert len(by_scope.structured_content["sessions"]) == 1
    assert len(by_capability.structured_content["sessions"]) == 1


@pytest.mark.anyio
async def test_deregister_round_trip(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        registered = await client.call_tool("directory_register", {"scope": "a"})
        handle = registered.structured_content["session"]["handle"]
        secret = registered.structured_content["session_secret"]

        deregistered = await client.call_tool(
            "directory_deregister", {"handle": handle, "session_secret": secret}
        )
        assert deregistered.structured_content["deregistered"] is True

        listing = await client.call_tool("directory_list", {})
    assert listing.structured_content["sessions"] == []
