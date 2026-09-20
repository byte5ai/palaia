"""Tool-ergonomics + IDENTITY acceptance tests for the Telegram tool family
(issue #411) — the same treatment ``test_stash_tools.py`` gives the stash
family: annotations lint, alias absorption, dual text/json output, and an
IDENTITY line that says what this family is *for*.

It also closes the second acceptance criterion end to end — "an agent sends a
reply through the tool; it appears in the originating chat, threaded to the
original message" — through a real ``fastmcp.Client`` against the real tool
server, with only the Bot API faked.

Lives here rather than under ``tests/gateway/`` (where the stash and
messenger tool tests sit) for one plain reason: ``tests/`` is not a package,
so a module under ``tests/gateway/`` cannot import this package's shared
fakes — and duplicating the fake Bot API to satisfy a directory convention
would be the worse trade.
"""

from __future__ import annotations

import pytest
from fastmcp import Client

from palaia_hub.gateway.telegram_tools import (
    TELEGRAM_IDENTITY,
    TELEGRAM_TOOL_ACTIONS,
    build_telegram_server,
)
from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.service import TelegramService

from .conftest import BOT_A_TOKEN, TWO_BOT_SETTINGS, FakeBotApi, FakeSecrets


@pytest.fixture
def server(service: TelegramService):  # noqa: ANN201 - fastmcp.FastMCP
    return build_telegram_server(service, profile="default")


@pytest.mark.anyio
async def test_every_action_is_exposed_as_a_tool(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == set(TELEGRAM_TOOL_ACTIONS)


@pytest.mark.anyio
async def test_annotations_lint_every_tool_declares_both_hints(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    assert tools
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.readOnlyHint is not None, f"{tool.name} missing readOnlyHint"
        assert tool.annotations.destructiveHint is not None, f"{tool.name} missing destructiveHint"


@pytest.mark.anyio
async def test_only_list_chats_is_read_only(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert tools["telegram_list_chats"].annotations.readOnlyHint is True
    for name in ("telegram_send", "telegram_reply", "telegram_edit", "telegram_delete"):
        assert tools[name].annotations.readOnlyHint is False


@pytest.mark.anyio
async def test_sending_is_not_advertised_as_idempotent(server) -> None:  # noqa: ANN001
    """Calling it twice sends two messages to a real person; a client that
    retried on a timeout because the annotation said 'idempotent' would be
    doing so on this family's word."""
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert tools["telegram_send"].annotations.idempotentHint is False
    assert tools["telegram_reply"].annotations.idempotentHint is False


@pytest.mark.anyio
async def test_every_description_carries_the_identity_line(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert TELEGRAM_IDENTITY in (tool.description or "")


def test_the_identity_line_says_this_family_reaches_people_not_agents() -> None:
    assert "people" in TELEGRAM_IDENTITY
    assert "messenger tools" in TELEGRAM_IDENTITY


@pytest.mark.anyio
async def test_a_send_returns_both_a_sentence_and_a_structured_result(
    server, api: FakeBotApi  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "telegram_send", {"bot": "support", "chat": "-1001", "text": "hello"}
        )
    assert result.data["message_id"] == api.sent[0]["message_id"]
    assert "sent message" in result.content[0].text


@pytest.mark.anyio
async def test_a_reply_through_the_tool_is_threaded_in_the_originating_chat(
    server, api: FakeBotApi  # noqa: ANN001
) -> None:
    """The issue's second acceptance criterion, through the real tool."""
    async with Client(server) as client:
        result = await client.call_tool(
            "telegram_reply",
            {
                "bot": "support",
                "chat": "-1001",
                "text": "on it",
                "reply_to_message_id": 1234,
            },
        )
    assert api.sent[0]["chat_id"] == "-1001"
    assert api.sent[0]["reply_to_message_id"] == 1234
    assert result.data["reply_to_message_id"] == 1234


@pytest.mark.anyio
async def test_aliases_are_absorbed_but_not_published(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await client.call_tool(
            "telegram_send", {"bot_key": "support", "chat_id": "-1001", "message": "via aliases"}
        )
        tools = {t.name: t for t in await client.list_tools()}
    published = set(tools["telegram_send"].inputSchema["properties"])
    assert published == {"bot", "chat", "text"}


@pytest.mark.anyio
async def test_list_chats_reports_the_routing_table(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool("telegram_list_chats", {})
    chats = {(row["bot"], row["chat"]): row for row in result.data["chats"]}
    assert chats[("support", "-1001")]["destination"] == "messenger:ops-agent"
    assert "messenger:ops-agent" in result.content[0].text


@pytest.mark.anyio
async def test_a_refusal_comes_back_as_a_tool_error_not_an_exception(
    api: FakeBotApi,
) -> None:
    """A profile with no grant gets an MCP-level error naming itself — the
    same convention the stash and messenger families follow."""
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS),
        api,
        FakeSecrets({"telegram_support": BOT_A_TOKEN}),
    )
    server = build_telegram_server(service, profile="unlisted")
    async with Client(server) as client:
        result = await client.call_tool(
            "telegram_send",
            {"bot": "support", "chat": "-1001", "text": "hi"},
            raise_on_error=False,
        )
    assert result.is_error
    assert "unlisted" in result.content[0].text
    assert api.sent == []


@pytest.mark.anyio
async def test_the_profile_is_not_a_tool_argument(server, api: FakeBotApi) -> None:  # noqa: ANN001
    """There is no ambient caller identity here, and no caller-supplied one
    either: the profile a server sends as is fixed when it is built, so it is
    not in any tool's schema and a call that tries to pass one is refused."""
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
        result = await client.call_tool(
            "telegram_send",
            {"bot": "support", "chat": "-1001", "text": "hi", "profile": "elsewhere"},
            raise_on_error=False,
        )
    for name in TELEGRAM_TOOL_ACTIONS:
        assert "profile" not in tools[name].inputSchema.get("properties", {})
    assert result.is_error
    assert api.sent == []


@pytest.mark.anyio
async def test_an_over_long_message_is_a_tool_error_naming_the_limit(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool(
            "telegram_send",
            {"bot": "support", "chat": "-1001", "text": "x" * 5000},
            raise_on_error=False,
        )
    assert result.is_error
    assert "4096" in result.content[0].text


@pytest.mark.anyio
async def test_no_tool_result_carries_a_token(server, api: FakeBotApi) -> None:  # noqa: ANN001
    async with Client(server) as client:
        for name, args in (
            ("telegram_list_chats", {}),
            ("telegram_send", {"bot": "support", "chat": "-1001", "text": "hi"}),
        ):
            result = await client.call_tool(name, args, raise_on_error=False)
            assert BOT_A_TOKEN not in repr(result)
