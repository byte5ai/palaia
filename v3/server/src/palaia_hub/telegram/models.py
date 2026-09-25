"""The Telegram connector's schema (issue #411): what an operator configures,
and what one inbound message becomes on the hub side.

**Import-free with respect to the rest of ``palaia_hub``**, the same rule
:mod:`palaia_hub.upstream.models` follows and for the same reason:
:mod:`palaia_hub.config` imports :class:`TelegramSettings` directly rather
than keeping a hand-maintained twin of it, and ``config.py`` must stay
importable without pulling httpx/fastapi/fastmcp in behind it. Nothing here
may import :mod:`palaia_hub.telegram.api` (httpx) or ``.service``.

**No credential ever appears in this module.** A bot names the *secret* that
holds its Bot API token (:attr:`TelegramBotConfig.token_secret`) and, in
webhook mode, the *secret* that holds the value Telegram must echo in its
``X-Telegram-Bot-Api-Secret-Token`` header
(:attr:`TelegramBotConfig.webhook_secret`). Both are looked up at call time
through :class:`palaia_hub.upstream.secrets.SecretStore`, so this model —
and therefore ``config.yaml``, which is plain text and gets copied around —
carries names only. That is the first of the three halves of the issue's
"a bot token never appears in config, logs, or tool output"; the other two
live in :mod:`palaia_hub.telegram.api` (an error never quotes the URL it
built) and :mod:`palaia_hub.logging` (the token *shape* is redacted even if
something else leaks one).

**Chat references are strings, always.** Telegram's own ids are 64-bit
integers and negative for groups/supergroups/channels, which YAML is happy
to mangle in surprising ways; a channel can also be addressed as
``@publicname``, which is not an integer at all. One string type for both,
normalised by :func:`normalise_chat_ref`, means a routing table and a send
call compare the same way whatever the operator typed.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: A bot's hub-side key: what ``config.yaml`` files it under, what a routing
#: rule names, and what an agent passes to ``telegram_send``. Never the bot's
#: Telegram username and never its token — an operator renaming a bot on
#: Telegram must not have to re-point every route.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: A public chat/channel reference (``@name``). Telegram's own rule: 5-32
#: characters, letters/digits/underscore.
_USERNAME_RE = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")

#: A numeric chat id, optionally negative (groups, supergroups, channels).
_CHAT_ID_RE = re.compile(r"^-?\d{1,19}$")

#: The routing wildcard: "every chat this bot receives from that no more
#: specific rule claims". Spelled out rather than an empty string so a
#: catch-all route is visible at a glance in ``config.yaml``.
CHAT_WILDCARD = "*"

#: The ``allowed_updates`` this connector asks Telegram for. Narrow on
#: purpose: everything else (callback queries, inline queries, poll answers,
#: chat-member changes) is out of scope for the first cut, and asking for an
#: update type nothing handles only costs bandwidth and invites a reviewer to
#: assume it is wired.
ALLOWED_UPDATES: tuple[str, ...] = (
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
)

#: Telegram's own hard cap on one outbound text message, in characters.
#: Enforced here rather than discovered as a 400 from the Bot API, so an
#: agent gets an error naming the limit instead of a remote failure.
MAX_MESSAGE_CHARS = 4096

#: How many outbound messages the service remembers, so an agent can edit or
#: delete what it sent. One ledger for the whole connector, not one per bot:
#: entries are keyed by ``(bot, chat, message)`` and the oldest is evicted
#: first whichever bot sent it. See
#: :class:`palaia_hub.telegram.service.SentLedger`.
DEFAULT_SENT_LEDGER_SIZE = 500

DestinationKind = Literal["messenger", "inbox", "event"]

TransportKind = Literal["polling", "webhook"]


class TelegramConfigError(ValueError):
    """A ``telegram:`` section that is structurally valid but unsatisfiable —
    a route naming a bot that is not configured, a grant naming one, a
    webhook bot with no ``webhook_secret``.

    Raised by :meth:`TelegramSettings.check_consistency`, which
    :class:`palaia_hub.config.HubConfig` runs at load time so the operator
    hears about it when they save the file, not when the first message
    arrives.
    """


def normalise_chat_ref(ref: str) -> str:
    """Return ``ref`` in the one form routing and sending both compare on.

    A numeric id keeps its digits and sign; a ``@name`` is lowercased (usernames
    are case-insensitive on Telegram, and an operator who typed ``@Ops`` must
    match the ``@ops`` the API reports); the wildcard passes through.

    Raises:
        TelegramConfigError: the reference is neither, so it could never
            match anything — a silent never-matching route is the worst
            possible failure mode for a routing table.
    """
    text = ref.strip()
    if text == CHAT_WILDCARD:
        return CHAT_WILDCARD
    if _CHAT_ID_RE.match(text):
        return text
    lowered = text.lower()
    if _USERNAME_RE.match(lowered):
        return lowered
    raise TelegramConfigError(
        f"{ref!r} is not a usable chat reference. Fix: use the numeric chat id "
        f"(e.g. -1001234567890 — the dashboard and the telegram.message.dropped "
        f"event both print it), a public @name, or {CHAT_WILDCARD!r} for every "
        "chat this bot receives from."
    )


class TelegramBotConfig(BaseModel):
    """One Telegram bot this hub serves.

    A hub runs several of these side by side — that is the point of the
    ``(bot, chat)`` routing key: a message through the ``support`` bot in the
    ``ops`` channel can land somewhere else than one through the ``personal``
    bot in a direct chat.
    """

    model_config = ConfigDict(extra="forbid")

    #: This bot's hub-side key. See :data:`_KEY_RE`.
    key: str
    #: The name of the secret holding this bot's Bot API token. Never the
    #: token — see the module docstring.
    token_secret: str
    #: Display name for the dashboard. ``None`` shows the key.
    label: str | None = None
    #: How updates reach the hub. ``polling`` works behind NAT and in
    #: ``locked`` mode, and is the default for exactly that reason;
    #: ``webhook`` needs a public URL and therefore a ``cloud``/``open`` hub.
    transport: TransportKind = "polling"
    #: In ``webhook`` transport: the name of the secret holding the value
    #: Telegram echoes in ``X-Telegram-Bot-Api-Secret-Token``. Required for
    #: a webhook bot — an unverified webhook endpoint is an open inbox for
    #: anyone who guesses the bot key.
    webhook_secret: str | None = None
    #: Switch the bot off without deleting its routes.
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError(
                f"telegram bot key {value!r} must be 1-64 characters of "
                "lowercase letters, digits, '_' or '-', starting with a letter "
                "or digit"
            )
        return value

    @model_validator(mode="after")
    def _check_webhook_secret(self) -> TelegramBotConfig:
        if self.transport == "webhook" and not (self.webhook_secret or "").strip():
            raise ValueError(
                f"telegram bot {self.key!r} uses webhook transport but names no "
                "webhook_secret. Fix: store a random value in the secret store "
                "(PUT /api/secrets/<name>), name it here, and pass the same "
                "value as secret_token when you call Telegram's setWebhook — "
                "without it the endpoint accepts an update from anyone who "
                "guesses the bot key."
            )
        return self


class TelegramDestination(BaseModel):
    """Where a routed message lands: one of the hub's existing surfaces.

    Three kinds, and no fourth, because the issue's fourth ("an automation
    trigger") already *is* one of these: automations fire off the hub's event
    bus (:mod:`palaia_hub.automations.dispatcher` subscribes to it), so
    ``kind: event`` is how a Telegram message triggers an automation. Stated
    here rather than discovered by an operator who wrote ``kind: automation``
    and got a validation error with no hint.
    """

    model_config = ConfigDict(extra="forbid")

    kind: DestinationKind
    #: ``messenger``: the recipient handle, or a broadcast query
    #: (``*``/``capability:<tag>``) — whatever
    #: :meth:`palaia_hub.messenger.service.MessengerService.send_as_owner`
    #: accepts. The envelope is sent *as the owner*: a Telegram message is
    #: the human talking, and the human has no session handle to speak from.
    to: str | None = None
    #: ``messenger``: the envelope type and urgency to mint. ``inform`` by
    #: default — a relayed message is news, not an order.
    message_type: Literal["request", "inform", "question", "handoff", "broadcast"] = "inform"
    urgency: Literal["low", "normal", "high"] = "normal"
    #: ``inbox``: which registered vault's ``inbox/`` the note lands in.
    vault: str | None = None
    #: ``event``: a short label distinguishing this route's events from
    #: another's, carried as ``data.label``. ``None`` uses the route's bot
    #: and chat, which is what a single-route hub wants anyway.
    label: str | None = None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> TelegramDestination:
        if self.kind == "messenger" and not (self.to or "").strip():
            raise ValueError(
                "a messenger destination needs `to`: the handle (or broadcast "
                "query) the envelope is addressed to."
            )
        if self.kind == "inbox" and not (self.vault or "").strip():
            raise ValueError(
                "an inbox destination needs `vault`: which registered vault's "
                "inbox/ the capture lands in."
            )
        if self.kind != "messenger" and self.to is not None:
            raise ValueError(f"`to` is only meaningful for kind: messenger, not {self.kind!r}")
        if self.kind != "inbox" and self.vault is not None:
            raise ValueError(f"`vault` is only meaningful for kind: inbox, not {self.kind!r}")
        return self

    def describe(self) -> str:
        """A one-line, credential-free rendering for logs and events."""
        if self.kind == "messenger":
            return f"messenger:{self.to}"
        if self.kind == "inbox":
            return f"inbox:{self.vault}"
        return "event"


class TelegramRoute(BaseModel):
    """One ``(bot, chat) → destination`` rule.

    Order in ``config.yaml`` does not decide which rule wins — specificity
    does, resolved by :class:`palaia_hub.telegram.routing.RoutingTable`. An
    operator reordering the list never silently changes where a message
    goes.
    """

    model_config = ConfigDict(extra="forbid")

    bot: str
    #: A numeric chat id, a public ``@name``, or :data:`CHAT_WILDCARD`.
    chat: str = CHAT_WILDCARD
    destination: TelegramDestination

    @field_validator("chat")
    @classmethod
    def _check_chat(cls, value: str) -> str:
        return normalise_chat_ref(value)


class TelegramGrant(BaseModel):
    """What one MCP profile may *send* through: the outbound fence.

    Default-deny, and deliberately keyed by gateway profile path rather than
    by session handle: the profile is what an operator actually configures
    and what a client's token is scoped to, and it is already the unit the
    rest of the gateway authorises on. A profile with no grant here can call
    ``telegram_send`` and will be refused by name — there is no implicit
    "everything" for an unlisted profile.

    The default-deny is at the level of the *entry*, not the fields: writing
    an entry for a profile and leaving ``bots``/``chats`` unset means "any
    configured bot, any chat", because that is what an operator who bothered
    to name the profile and nothing else meant. Narrowing is done by listing.
    An entry with an empty list — ``chats: []`` — denies everything, and is
    how a profile is switched off without deleting its entry.
    """

    model_config = ConfigDict(extra="forbid")

    #: The gateway profile path (``gateway.profiles[].path``).
    profile: str
    #: Bot keys this profile may address. Unset means every configured bot.
    bots: list[str] = Field(default_factory=lambda: [CHAT_WILDCARD])
    #: Chat references this profile may address. Unset means every chat.
    chats: list[str] = Field(default_factory=lambda: [CHAT_WILDCARD])

    @field_validator("chats")
    @classmethod
    def _check_chats(cls, value: list[str]) -> list[str]:
        return [normalise_chat_ref(chat) for chat in value]

    def allows(self, bot: str, chat: str) -> bool:
        """Whether this grant covers sending to ``chat`` through ``bot``."""
        bot_ok = CHAT_WILDCARD in self.bots or bot in self.bots
        chat_ok = CHAT_WILDCARD in self.chats or normalise_chat_ref(chat) in self.chats
        return bot_ok and chat_ok


class TelegramSettings(BaseModel):
    """The ``telegram:`` section of ``config.yaml``.

    Absent (``None`` on :class:`palaia_hub.config.HubConfig`, the default)
    means the connector does not exist: no poller, no webhook endpoint, and
    every profile's ``telegram: true`` flag mounts nothing. Present with an
    empty ``bots`` list is the same thing said out loud.
    """

    model_config = ConfigDict(extra="forbid")

    bots: list[TelegramBotConfig] = Field(default_factory=list)
    routes: list[TelegramRoute] = Field(default_factory=list)
    #: The outbound fence. See :class:`TelegramGrant`.
    grants: list[TelegramGrant] = Field(default_factory=list)
    #: Long-poll timeout in seconds handed to ``getUpdates``. Telegram holds
    #: the request open this long when nothing is happening, which is what
    #: makes long polling cheap rather than a busy loop.
    poll_timeout_seconds: float = Field(30.0, gt=0, le=60)

    @model_validator(mode="after")
    def _check_unique_bots(self) -> TelegramSettings:
        seen: set[str] = set()
        for bot in self.bots:
            if bot.key in seen:
                raise ValueError(
                    f"telegram bot key {bot.key!r} is configured twice; keys "
                    "address a bot everywhere (routes, grants, tool calls) and "
                    "must be unique"
                )
            seen.add(bot.key)
        return self

    @model_validator(mode="after")
    def _check_unique_routes(self) -> TelegramSettings:
        seen: set[tuple[str, str]] = set()
        for route in self.routes:
            key = (route.bot, route.chat)
            if key in seen:
                raise ValueError(
                    f"telegram route {route.bot}/{route.chat} is configured "
                    "twice; one (bot, chat) has exactly one destination — put "
                    "the second one on a different chat, or fan out from the "
                    "destination instead"
                )
            seen.add(key)
        return self

    def bot(self, key: str) -> TelegramBotConfig | None:
        """The bot configured under ``key``, or ``None``."""
        for bot in self.bots:
            if bot.key == key:
                return bot
        return None

    def grant(self, profile: str) -> TelegramGrant | None:
        """The grant for ``profile``, or ``None`` — which means *deny*."""
        for grant in self.grants:
            if grant.profile == profile:
                return grant
        return None

    def check_consistency(self) -> None:
        """Refuse a section whose cross-references do not resolve.

        Structural validity is pydantic's job and already done by the time
        this runs; this is the layer above it — a route pointing at a bot
        that is not configured is a message that will silently never be
        delivered, which is exactly the class of mistake a config file
        should not be able to hold quietly.

        Raises:
            TelegramConfigError: naming the offending route or grant.
        """
        keys = {bot.key for bot in self.bots}
        for route in self.routes:
            if route.bot not in keys:
                raise TelegramConfigError(
                    f"telegram route for {route.bot}/{route.chat} names bot "
                    f"{route.bot!r}, which is not configured under telegram.bots "
                    f"(configured: {sorted(keys) or 'none'}). Fix: add the bot, or "
                    "remove the route — as written, nothing would ever match it."
                )
        for grant in self.grants:
            unknown = [b for b in grant.bots if b != CHAT_WILDCARD and b not in keys]
            if unknown:
                raise TelegramConfigError(
                    f"telegram grant for profile {grant.profile!r} names bot(s) "
                    f"{unknown}, which are not configured under telegram.bots "
                    f"(configured: {sorted(keys) or 'none'})."
                )


# -- the normalised inbound record --------------------------------------------


class Attachment(BaseModel):
    """A media reference on an inbound message — a *reference*, never bytes.

    Downloading is explicitly out of scope for the first cut (the issue says
    so), and this shape is what makes that honest: the hub records which file
    Telegram is holding and how big it is, so a later cut can fetch it
    without re-reading the update.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["photo", "document", "audio", "video", "voice", "animation", "sticker"]
    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class InboundMessage(BaseModel):
    """One inbound Telegram message, normalised into the hub's own shape.

    Every field a route, a destination or the dashboard needs, and nothing
    Telegram-specific beyond the ids required to answer: *which bot received
    it, which chat it came from, who sent it, what it says, which message it
    is, and when*. The raw update is not kept — it is a moving target
    (Telegram adds fields continuously) and a copy of it in three surfaces is
    three things to keep in sync.
    """

    model_config = ConfigDict(extra="forbid")

    #: The hub-side bot key that received this — not the bot's Telegram id.
    bot: str
    update_id: int
    message_id: int
    chat_id: int
    chat_type: str
    chat_title: str | None = None
    #: The chat's public ``@name`` without the ``@``, when it has one.
    chat_username: str | None = None
    sender_id: int | None = None
    sender_username: str | None = None
    sender_name: str | None = None
    #: The message text (or a media caption). Empty for a media-only message.
    text: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    #: Telegram's own timestamp, unix seconds.
    date: float = 0.0
    #: The message this one replies to, inside Telegram.
    reply_to_message_id: int | None = None
    #: Whether this arrived as an ``edited_message``/``edited_channel_post``.
    edited: bool = False

    @property
    def chat_ref(self) -> str:
        """This chat as a routing key: its numeric id, always.

        The id, not the ``@name``, because every chat has one and only some
        have a name — :class:`palaia_hub.telegram.routing.RoutingTable` tries
        the name too, for the operator's convenience, but the id is the
        identity.
        """
        return str(self.chat_id)

    @property
    def chat_label(self) -> str:
        """A short human label for a subject line or a log: title, ``@name``
        or the bare id, in that order of usefulness."""
        if self.chat_title:
            return self.chat_title
        if self.chat_username:
            return f"@{self.chat_username}"
        return str(self.chat_id)

    @property
    def sender_label(self) -> str:
        """Who sent it, as a human would say it. ``"(channel)"`` when
        Telegram reports no sender, which is the normal case for a post in a
        broadcast channel."""
        if self.sender_name and self.sender_username:
            return f"{self.sender_name} (@{self.sender_username})"
        if self.sender_name:
            return self.sender_name
        if self.sender_username:
            return f"@{self.sender_username}"
        return "(channel)"

    def metadata(self) -> dict[str, object]:
        """This message **without its text**, for the event bus.

        The same rule SPEC-403 fixed for envelopes
        (:class:`palaia_hub.messenger.models.EnvelopeMetadata`: "a body on a
        bus is a body in every webhook receiver's logs") applied to a
        Telegram message, which is if anything more sensitive — it is a
        human's words, not an agent's. ``text_chars`` is the honest
        substitute: how much there is to read, without reading it.

        The one route that *does* put text on the bus is ``kind: event``, and
        an operator gets that only by writing it down — see
        :meth:`palaia_hub.telegram.service.TelegramService.handle_update`.
        """
        return {
            "bot": self.bot,
            "chat_id": self.chat_id,
            "chat_type": self.chat_type,
            "chat_username": self.chat_username,
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "sender_username": self.sender_username,
            "text_chars": len(self.text),
            "attachments": [a.kind for a in self.attachments],
            "reply_to_message_id": self.reply_to_message_id,
            "edited": self.edited,
            "date": self.date,
        }


class SentMessage(BaseModel):
    """What an outbound call actually did — the tool's structured result."""

    model_config = ConfigDict(extra="forbid")

    bot: str
    chat_id: int
    message_id: int
    #: The Telegram message this one answers, when it is a reply.
    reply_to_message_id: int | None = None
    text_chars: int = 0


class DeletedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: str
    chat_id: int
    message_id: int
    deleted: bool


class DispatchOutcome(BaseModel):
    """What the hub did with one inbound message.

    Returned by
    :meth:`palaia_hub.telegram.service.TelegramService.handle_update` and
    carried into the ``telegram.message.*`` events. ``routed=False`` is a
    perfectly ordinary outcome — a bot in a chat nobody wrote a rule for —
    and is reported rather than logged away, because "my message vanished"
    is the first thing an operator will ask about.
    """

    model_config = ConfigDict(extra="forbid")

    bot: str
    #: ``None`` when the update was not a message at all (a callback query,
    #: say): nothing to route, nothing dropped.
    message: InboundMessage | None = None
    routed: bool = False
    destination: str | None = None
    delivered: bool = False
    #: One line naming what happened, in the operator's language. Never a
    #: stack trace and never a credential.
    detail: str = ""


class ChatInfo(BaseModel):
    """One addressable chat, as ``telegram_list_chats`` reports it.

    Built from configuration, not from a Bot API call: Telegram has no
    "list my chats" method (a bot learns a chat exists by receiving from it),
    and an agent needs to know what it is *allowed* to address anyway — which
    is a hub-side fact, not a Telegram one.
    """

    model_config = ConfigDict(extra="forbid")

    bot: str
    chat: str
    #: Where inbound traffic from this chat goes, or ``None`` when no route
    #: claims it — visible to the agent on purpose: "I can send here but
    #: nothing routes back" is worth knowing before starting a conversation.
    destination: str | None = None
    #: Whether the calling profile may send here.
    can_send: bool = True


# -- what the dashboard panel shows (issue #439) -----------------------------


#: How many inbound messages the dashboard's "Recent messages" list keeps —
#: one ring for the whole hub, not one per bot, newest pushing the oldest
#: out. In memory only: a restart empties it, which is the point (ADR-006:
#: no message store).
DEFAULT_RECENT_SIZE = 50


class RecentMessage(BaseModel):
    """What the hub did with one inbound message, as the dashboard lists it.

    Picked from :meth:`InboundMessage.metadata` — and deliberately narrower
    than it: no sender, and **no field the text could go in**, so the list
    stays metadata-only by construction rather than by remembering not to
    fill one in (the same shape :class:`SentMessage` has for a token).
    ``candidates`` is what replaces "read the log line" for an operator
    writing their first route: the chat keys a rule could have used.
    """

    model_config = ConfigDict(extra="forbid")

    #: When the hub handled it (hub clock, unix seconds) — not Telegram's
    #: own ``date``, which a delayed redelivery would make look old.
    at: float
    bot: str
    chat_id: int
    chat_type: str
    chat_username: str | None = None
    message_id: int
    text_chars: int = 0
    routed: bool = False
    #: :meth:`TelegramDestination.describe` of the route that claimed it.
    destination: str | None = None
    delivered: bool = False
    #: The outcome's one line, token-scrubbed and cut short.
    detail: str = ""
    #: A dropped message only: the chat keys tried, most specific first.
    candidates: list[str] | None = None


class BotCheck(BaseModel):
    """The last on-demand connection check of one bot (``getMe``).

    Cached by :class:`palaia_hub.telegram.runtime.TelegramRuntime` until
    the next check, so the dashboard can show it on every refetch without
    ever calling Telegram from a read.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    #: The bot's Telegram ``@username`` (without the ``@``), when it answered.
    username: str | None = None
    checked_at: float
    #: Why it failed, token-scrubbed and cut short. ``None`` when ``ok``.
    error: str | None = None


# -- errors -------------------------------------------------------------------


class TelegramError(Exception):
    """Base for every caller-facing connector failure.

    Turned into a ``ToolResult(is_error=True, ...)`` by
    :mod:`palaia_hub.gateway.telegram_tools` and never allowed to escape as
    an uncaught exception — the same convention ``StashError`` and
    ``MessengerError`` follow. Every subclass carries a message naming the
    fix, and **none of them ever carries a token**: see
    :mod:`palaia_hub.telegram.api`.
    """


class UnknownBotError(TelegramError):
    """No bot is configured under that key (or it is switched off)."""


class NotPermittedError(TelegramError):
    """The calling profile has no grant covering this bot/chat."""


class MissingSecretError(TelegramError):
    """The bot is configured, but the secret it names holds nothing.

    The one failure an operator hits on day one — the bot was added to
    ``config.yaml`` before its token was put in the secret store — so the
    message names the store and the secret, and nothing else.
    """


class MessageTooLongError(TelegramError):
    """The outbound text is over :data:`MAX_MESSAGE_CHARS`."""


class NotOurMessageError(TelegramError):
    """Edit/delete was asked for a message this hub did not send.

    Telegram's own API would also refuse most of these, but not all — a bot
    can delete another member's message in a group it administrates. That is
    group moderation, which the issue puts out of scope, so the fence is
    here rather than left to the remote end.
    """


__all__ = [
    "ALLOWED_UPDATES",
    "CHAT_WILDCARD",
    "DEFAULT_RECENT_SIZE",
    "DEFAULT_SENT_LEDGER_SIZE",
    "MAX_MESSAGE_CHARS",
    "Attachment",
    "BotCheck",
    "ChatInfo",
    "DeletedMessage",
    "DestinationKind",
    "DispatchOutcome",
    "InboundMessage",
    "MessageTooLongError",
    "MissingSecretError",
    "NotOurMessageError",
    "NotPermittedError",
    "RecentMessage",
    "SentMessage",
    "TelegramBotConfig",
    "TelegramConfigError",
    "TelegramDestination",
    "TelegramError",
    "TelegramGrant",
    "TelegramRoute",
    "TelegramSettings",
    "TransportKind",
    "UnknownBotError",
    "normalise_chat_ref",
]
