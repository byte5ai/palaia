"""The Telegram tool family as a mountable FastMCP server (issue #411).

Five tools — ``telegram_list_chats``, ``telegram_send``, ``telegram_reply``,
``telegram_edit``, ``telegram_delete`` — following the patterns the stash and
messenger families established (consistency beats invention, as
:mod:`palaia_hub.gateway.stash_tools` puts it):

- **Behavior annotations** on every tool, so a client can tell a read from a
  send without reading prose.
- **Alias absorption**: ``bot`` also accepts ``bot_key``; ``chat`` also
  accepts ``chat_id``/``channel``; ``text`` also accepts ``message``/``body``.
  The published schema still shows only the canonical name.
- **Dual text/json output**: a human-readable ``content`` string alongside
  the structured payload.
- **Its own IDENTITY line**, opening every description: this family talks to
  *people*, on their phones, and a model should know that before it composes
  anything.

**Built per profile, and the profile is an argument, not a lookup.** Every
tool here closes over the ``profile`` path this server was built for and
passes it into the service, which refuses anything the profile's
:class:`~palaia_hub.telegram.models.TelegramGrant` does not cover. There is
no ambient "who is calling" — a mis-mounted server can only ever send as the
profile it was built for.

**No tool reads inbound traffic.** Deliberate, and recorded as an ADR
(``v3/decisions/006-telegram-reading-surface.md``): inbound messages reach
agents through the routing table's destinations — a messenger envelope, a
vault ``inbox/`` note, a hub event — not through a polling tool. See the ADR
for why an MCP App channel view was considered and deferred rather than
quietly skipped (MASTERPLAN §4 rule 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, Field
from starlette.types import ASGIApp

from ..auth.enforcement import missing_telegram_scope_error
from ..telegram.models import ChatInfo, TelegramError
from ..telegram.service import TelegramService

TELEGRAM_TOOL_ACTIONS: tuple[str, ...] = (
    "telegram_list_chats",
    "telegram_send",
    "telegram_reply",
    "telegram_edit",
    "telegram_delete",
)

TELEGRAM_IDENTITY = (
    "IDENTITY: this is the Telegram connector — a channel to actual people, "
    "on their phones, through bots this hub's owner configured. A message "
    "sent here is read by a human and cannot be unsent once they have seen "
    "it; write accordingly, and do not use it to talk to other agents (the "
    "messenger tools are for that). You can only address the bots and chats "
    "the owner granted this profile; everything else is refused by name. "
    "Incoming messages are NOT read through these tools — they are routed by "
    "the owner's routing table to your messenger inbox, a vault inbox/ note, "
    "or a hub event."
)

BotParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("bot", "bot_key"),
        description="The hub's own name for the bot to speak through (not its Telegram username).",
    ),
]
ChatParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("chat", "chat_id", "channel"),
        description="The numeric chat id, or a public @name.",
    ),
]
TextParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("text", "message", "body"),
        description="The message text. Plain text; at most 4096 characters.",
    ),
]
MessageIdParam = Annotated[
    int,
    Field(
        validation_alias=AliasChoices("message_id", "id"),
        description="The Telegram message id, as returned by telegram_send.",
    ),
]


def _error_result(exc: TelegramError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _chats_summary(rows: list[ChatInfo]) -> str:
    if not rows:
        return (
            "no Telegram chats are reachable from this profile — the owner has "
            "granted it none, or no bot is configured"
        )
    lines = [
        f"{row.bot}/{row.chat}"
        + (f" → {row.destination}" if row.destination else "")
        + ("" if row.can_send else " (read-only: sending not granted)")
        for row in rows
    ]
    return f"{len(rows)} Telegram chat(s):\n" + "\n".join(lines)


def build_telegram_server(
    service: TelegramService, *, profile: str, auth: AuthProvider | None = None
) -> FastMCP:
    """Build the Telegram tool family for one gateway profile.

    Args:
        service: the hub-wide connector.
        profile: the gateway profile path these tools send as. Every call is
            authorised against this profile's grant — see the module
            docstring.
        auth: the profile's token verifier, when it has one.
    """
    server = FastMCP(name="palaia-telegram", instructions=TELEGRAM_IDENTITY, auth=auth)

    def desc(detail: str) -> str:
        return f"{TELEGRAM_IDENTITY}\n\n{detail}"

    def scope_error(action: str) -> ToolResult | None:
        message = missing_telegram_scope_error(action)
        return ToolResult(content=message, is_error=True) if message else None

    @server.tool(
        name="telegram_list_chats",
        description=desc(
            "List every Telegram chat this profile can see: which bot reaches "
            "it, where inbound traffic from it is routed, and whether this "
            "profile may send there. Built from the hub's configuration — "
            "Telegram itself has no 'list my chats' call. Start here rather "
            "than guessing a chat id."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def telegram_list_chats() -> ToolResult:
        if (err := scope_error("telegram_list_chats")) is not None:
            return err
        rows = service.list_chats(profile)
        return ToolResult(
            content=_chats_summary(rows),
            structured_content={"chats": [r.model_dump() for r in rows]},
        )

    @server.tool(
        name="telegram_send",
        description=desc(
            "Send a text message to a chat through one of the bots this "
            "profile may use. Returns the Telegram message id, which is what "
            "telegram_edit and telegram_delete take. Not idempotent: calling "
            "it twice sends two messages to a real person."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
        ),
    )
    async def telegram_send(bot: BotParam, chat: ChatParam, text: TextParam) -> ToolResult:
        if (err := scope_error("telegram_send")) is not None:
            return err
        try:
            sent = await service.send(profile=profile, bot=bot, chat=chat, text=text)
        except TelegramError as exc:
            return _error_result(exc)
        return ToolResult(
            content=f"sent message {sent.message_id} to chat {sent.chat_id} via bot {bot!r}",
            structured_content=sent,
        )

    @server.tool(
        name="telegram_reply",
        description=desc(
            "Reply to a specific message, threaded under it in the chat — the "
            "right tool when answering something a person sent, because they "
            "see your answer quoted under their own words. Same permissions "
            "as telegram_send."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
        ),
    )
    async def telegram_reply(
        bot: BotParam,
        chat: ChatParam,
        text: TextParam,
        reply_to_message_id: Annotated[
            int,
            Field(
                validation_alias=AliasChoices("reply_to_message_id", "reply_to", "in_reply_to"),
                description="The message id to thread this reply under.",
            ),
        ],
    ) -> ToolResult:
        if (err := scope_error("telegram_reply")) is not None:
            return err
        try:
            sent = await service.send(
                profile=profile,
                bot=bot,
                chat=chat,
                text=text,
                reply_to_message_id=reply_to_message_id,
            )
        except TelegramError as exc:
            return _error_result(exc)
        return ToolResult(
            content=(
                f"replied to message {reply_to_message_id} in chat {sent.chat_id} "
                f"as message {sent.message_id}"
            ),
            structured_content=sent,
        )

    @server.tool(
        name="telegram_edit",
        description=desc(
            "Replace the text of a message THIS profile sent earlier in this "
            "hub's current run. Someone else's message — including another "
            "profile's — is refused: editing those is group moderation, which "
            "this connector does not do."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
        ),
    )
    async def telegram_edit(
        bot: BotParam, chat: ChatParam, message_id: MessageIdParam, text: TextParam
    ) -> ToolResult:
        if (err := scope_error("telegram_edit")) is not None:
            return err
        try:
            sent = await service.edit(
                profile=profile, bot=bot, chat=chat, message_id=message_id, text=text
            )
        except TelegramError as exc:
            return _error_result(exc)
        return ToolResult(
            content=f"edited message {message_id} in chat {sent.chat_id}",
            structured_content=sent,
        )

    @server.tool(
        name="telegram_delete",
        description=desc(
            "Delete a message THIS profile sent. Irreversible, and the person "
            "may already have read it — Telegram does not un-notify. Same "
            "ownership fence as telegram_edit."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True
        ),
    )
    async def telegram_delete(
        bot: BotParam, chat: ChatParam, message_id: MessageIdParam
    ) -> ToolResult:
        if (err := scope_error("telegram_delete")) is not None:
            return err
        try:
            result = await service.delete(
                profile=profile, bot=bot, chat=chat, message_id=message_id
            )
        except TelegramError as exc:
            return _error_result(exc)
        text = (
            f"deleted message {message_id} in chat {result.chat_id}"
            if result.deleted
            else f"Telegram did not delete message {message_id} in chat {result.chat_id}"
        )
        return ToolResult(content=text, structured_content=result)

    return server


@dataclass
class TelegramGatewayASGI:
    """The Telegram server's mountable surface, mirroring
    :class:`palaia_hub.gateway.stash_tools.StashGatewayASGI`. ``lifespan``
    MUST be combined into whatever ASGI app ``app`` is mounted under."""

    app: ASGIApp
    lifespan: Any
    server: FastMCP


def build_telegram_gateway(
    service: TelegramService, *, profile: str, auth: AuthProvider | None = None
) -> TelegramGatewayASGI:
    """Build the Telegram server and its mountable ASGI app + lifespan."""
    server = build_telegram_server(service, profile=profile, auth=auth)
    asgi_app = server.http_app(path="/")
    return TelegramGatewayASGI(app=asgi_app, lifespan=asgi_app.lifespan, server=server)


__all__ = [
    "TELEGRAM_IDENTITY",
    "TELEGRAM_TOOL_ACTIONS",
    "TelegramGatewayASGI",
    "build_telegram_gateway",
    "build_telegram_server",
]
