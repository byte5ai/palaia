"""Tool-ergonomics acceptance tests for one vault's memory tool family
(SPEC-105 deliverable #4 / acceptance criteria: annotations-lint, alias
absorption, dual text/json output, leading purpose line, IDENTITY +
ai_assistant_guide).
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.gateway.vault_protocol import (
    APP_TOOL_ACTIONS,
    INBOX_TOOL_ACTIONS,
    MEMORY_TOOL_ACTIONS,
    RECALL_TOOL_ACTIONS,
)


@pytest.fixture
def vault_config() -> VaultMountConfig:
    return VaultMountConfig(
        key="work",
        name="work",
        purpose="Team knowledge for ACME engineering.",
    )


@pytest.fixture
def server(vault_config: VaultMountConfig):  # noqa: ANN201 - fastmcp.FastMCP, imported lazily
    return build_vault_server(vault_config, FakeVaultService())


@pytest.mark.anyio
async def test_every_action_is_exposed_as_a_tool(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    # SPEC-107 adds capture/inbox_status, SPEC-106 adds recall/build_context,
    # and SPEC-208 adds review_queue/review_decide/recall_pick to the same
    # server as the original eight memory actions (see
    # vault_protocol.INBOX_TOOL_ACTIONS's comment for why each is a separate
    # tuple rather than folded into MEMORY_TOOL_ACTIONS).
    assert names == (
        set(MEMORY_TOOL_ACTIONS)
        | set(INBOX_TOOL_ACTIONS)
        | set(RECALL_TOOL_ACTIONS)
        | set(APP_TOOL_ACTIONS)
    )


@pytest.mark.anyio
async def test_annotations_lint_every_tool_has_readonly_and_destructive_hints(
    server,  # noqa: ANN001
) -> None:
    """Acceptance criterion: 'every tool passes an annotations-lint'."""
    async with Client(server) as client:
        tools = await client.list_tools()
    assert tools, "expected at least one tool"
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} has no annotations"
        assert tool.annotations.readOnlyHint is not None, f"{tool.name} missing readOnlyHint"
        assert (
            tool.annotations.destructiveHint is not None
        ), f"{tool.name} missing destructiveHint"


@pytest.mark.anyio
async def test_annotations_lint_every_tool_description_leads_with_purpose(
    server, vault_config: VaultMountConfig  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description is not None
        assert tool.description.startswith(vault_config.purpose), (
            f"{tool.name}'s description does not lead with the vault purpose line: "
            f"{tool.description!r}"
        )


@pytest.mark.anyio
async def test_readonly_tools_are_marked_readonly_and_mutators_are_not(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    for name in ("search", "read", "list", "recent_activity", "inbox_status"):
        assert tools[name].annotations.readOnlyHint is True, name
    for name in ("write", "edit", "move", "delete", "capture"):
        assert tools[name].annotations.readOnlyHint is False, name


@pytest.mark.anyio
async def test_search_input_schema_shows_only_the_canonical_param_name(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    schema = tools["search"].inputSchema
    assert "query" in schema["properties"]
    assert "q" not in schema["properties"]
    assert "text" not in schema["properties"]


@pytest.mark.anyio
async def test_search_alias_absorption_q_and_text(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await server_write(client)
        for alias_key in ("q", "text", "query"):
            result = await client.call_tool("search", {alias_key: "onboarding"})
            assert result.is_error is not True, (alias_key, result.content)
            assert result.structured_content["query"] == "onboarding"


async def server_write(client: Client) -> None:  # noqa: ANN001
    await client.call_tool("write", {"title": "Onboarding", "body": "welcome to onboarding"})


@pytest.mark.anyio
async def test_folder_alias_absorption_dir_and_path_on_write(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        for alias_key, folder in (("dir", "team-a"), ("path", "team-b"), ("folder", "team-c")):
            result = await client.call_tool(
                "write", {"title": f"Note {folder}", "body": "x", alias_key: folder}
            )
            assert result.is_error is not True, (alias_key, result.content)
            assert result.structured_content["folder"] == folder


@pytest.mark.anyio
async def test_folder_alias_absorption_on_list(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await client.call_tool("write", {"title": "A", "body": "a", "folder": "work-notes"})
        for alias_key in ("dir", "path", "folder"):
            result = await client.call_tool("list", {alias_key: "work-notes"})
            assert result.is_error is not True
            assert result.structured_content["folder"] == "work-notes"
            assert len(result.structured_content["notes"]) == 1


@pytest.mark.anyio
async def test_write_returns_dual_text_and_json_output(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool("write", {"title": "Dual Output", "body": "hello"})

    # Text side: a human-readable summary string.
    assert result.content
    text_block = result.content[0]
    assert text_block.type == "text"
    assert "Dual Output" in text_block.text

    # JSON side: the structured note record, independently parseable.
    assert result.structured_content is not None
    assert result.structured_content["title"] == "Dual Output"
    assert result.structured_content["body"] == "hello"
    # And it really is valid JSON on its own, not just a Python dict.
    json.dumps(result.structured_content)


@pytest.mark.anyio
async def test_read_missing_permalink_is_a_tool_error_not_an_exception(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool(
            "read", {"permalink": "does/not-exist"}, raise_on_error=False
        )
    assert result.is_error is True


@pytest.mark.anyio
async def test_server_instructions_carry_an_identity_line(
    server, vault_config: VaultMountConfig  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        init = client.initialize_result
    assert init is not None
    assert init.instructions is not None
    assert init.instructions.startswith("IDENTITY:")
    assert vault_config.name in init.instructions


@pytest.mark.anyio
async def test_ai_assistant_guide_resource_is_served(
    server, vault_config: VaultMountConfig  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        resources = await client.list_resources()
        names = {r.name for r in resources}
        assert "ai_assistant_guide" in names

        guide_uri = next(r.uri for r in resources if r.name == "ai_assistant_guide")
        contents = await client.read_resource(guide_uri)
    assert contents
    assert vault_config.purpose in contents[0].text
