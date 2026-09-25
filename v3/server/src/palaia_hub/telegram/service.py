"""The Telegram connector's one service (issue #411): route inbound, fence
outbound, and never hold a token.

**Inbound** — :meth:`TelegramService.handle_update` is the single entry point
for both transports. The poller and the webhook route differ only in how an
update reaches this method; everything after that (normalise → resolve →
dispatch → emit) is one path, so "long polling and webhook mode behave the
same" is a property of the code rather than a promise in the docs.

**Destinations are protocols, not imports.** The connector talks to the
messenger and to a vault through :class:`MessengerSink` and
:class:`InboxSink` — two-method structural types a test satisfies with a
five-line fake. It deliberately does not import
:class:`~palaia_hub.messenger.service.MessengerService` or the vault engine:
this package must stay cheap to import and trivial to test, and a connector
that reached into three subsystems directly would be neither. (The one
concrete import is :data:`~palaia_hub.messenger.models.MAX_BODY_BYTES` — a
number, from a module that is pure pydantic, and the alternative was
duplicating a cap that must not drift.)

**Outbound is default-deny.** Every send/edit/delete names the calling
gateway profile, and a profile with no
:class:`~palaia_hub.telegram.models.TelegramGrant` is refused *by name*
rather than silently allowed. Edit and delete additionally require the
message to be one this hub sent (:class:`SentLedger`) — Telegram would let
a bot that administrates a group delete a member's message, and group
moderation is explicitly out of scope.

**The token never lands here either.** :attr:`TelegramService._secrets` is a
reader, not a cache: a token is fetched for the duration of one API call and
dropped. Nothing in this module logs one, and nothing puts one in a result —
:class:`~palaia_hub.telegram.models.SentMessage` has no field it could go
in, exactly as ``upstream.api``'s listing model has none for an upstream
credential.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Protocol

from ..messenger.models import MAX_BODY_BYTES
from .api import BotApi
from .models import (
    ALLOWED_UPDATES,
    DEFAULT_SENT_LEDGER_SIZE,
    MAX_MESSAGE_CHARS,
    ChatInfo,
    DeletedMessage,
    DispatchOutcome,
    InboundMessage,
    MessageTooLongError,
    MissingSecretError,
    NotOurMessageError,
    NotPermittedError,
    SentMessage,
    TelegramBotConfig,
    TelegramDestination,
    TelegramSettings,
    UnknownBotError,
    normalise_chat_ref,
)
from .routing import RoutingTable
from .updates import normalise_update

logger = logging.getLogger("palaia_hub.telegram.service")

#: Emitted for every inbound message, routed or not. Carries
#: :meth:`~palaia_hub.telegram.models.InboundMessage.metadata` — never the
#: text. See that method's docstring for why.
EVENT_RECEIVED = "telegram.message.received"

#: Emitted when no route claims a message. Carries the chat keys that *would*
#: have matched, so writing the missing rule is copy-and-paste.
EVENT_DROPPED = "telegram.message.dropped"

#: Emitted for every message an agent (or a destination) sends out.
EVENT_SENT = "telegram.message.sent"

#: Emitted by a ``kind: event`` route, and **only** by one. The one event in
#: this vocabulary that carries the message text, because an operator who
#: writes that route is asking for exactly that — see
#: :meth:`TelegramService._dispatch_event`.
EVENT_ROUTED = "telegram.routed"

#: How many characters of a message's first line become a messenger
#: envelope's subject before it is elided.
SUBJECT_PREVIEW_CHARS = 80


class SecretReader(Protocol):
    """The one method the connector needs of the encrypted secret store.

    A protocol rather than :class:`palaia_hub.upstream.secrets.SecretStore`
    itself so a test never touches a Fernet key or a SQLite file to assert
    something about routing.
    """

    def get(self, name: str) -> str | None:
        """The stored secret's value, or ``None`` if there is no such entry."""
        ...


class MessengerSink(Protocol):
    """What a ``kind: messenger`` destination needs of the messenger.

    Matches :meth:`palaia_hub.messenger.service.MessengerService.send_as_owner`
    structurally. *As the owner* is the right sender for a relayed Telegram
    message and not a shortcut: the human wrote it, and the human has no
    SPEC-402 session handle to speak from.
    """

    async def send_as_owner(
        self,
        *,
        message_type: Any,
        to: str,
        subject: str,
        body: str = "",
        urgency: Any = "normal",
        expects_reply: bool = False,
        refs: list[str] | None = None,
        reply_to: str | None = None,
        ttl_seconds: float | None = None,
        readable_vaults: frozenset[str] | None = None,
    ) -> Any: ...


class InboxSink(Protocol):
    """What a ``kind: inbox`` destination needs of a vault: the zero-friction
    capture the format spec's §7 ``inbox/`` already exists for."""

    async def capture(
        self,
        *,
        what_it_concerns: str,
        why_keep: str,
        content: str,
        source: str | None = None,
    ) -> Any: ...


class SentLedger:
    """The message ids this hub sent, so edit/delete can be fenced to them.

    Bounded and in-memory on purpose. Bounded, because an unbounded map keyed
    by every message a chatty bot ever sent is a slow leak; in-memory,
    because the fence it backs is a *narrowing* — losing an entry costs an
    agent the ability to edit an old message of its own, which is a refusal
    with a clear reason, not a security hole. Persisting it is a named
    follow-up, not a silent omission.
    """

    def __init__(self, capacity: int = DEFAULT_SENT_LEDGER_SIZE) -> None:
        self._capacity = max(1, capacity)
        self._entries: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        #: ``(bot, "@name")`` → the numeric chat id that ``@name`` turned out
        #: to be. Learned from a send's own reply, so an agent that addressed
        #: a channel by name can edit or delete through the same name it
        #: sent with instead of having to carry the id back.
        self._aliases: dict[tuple[str, str], int] = {}

    def record(
        self, *, bot: str, chat_id: int, message_id: int, profile: str, alias: str | None = None
    ) -> None:
        key = (bot, chat_id, message_id)
        self._entries[key] = profile
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        if alias:
            self._aliases[(bot, alias)] = chat_id

    def chat_id_for(self, *, bot: str, chat_ref: str) -> int | None:
        """``chat_ref`` as a numeric chat id: itself when it is one, else the
        id a previous send through ``bot`` proved it to be."""
        if chat_ref.lstrip("-").isdigit():
            return int(chat_ref)
        return self._aliases.get((bot, chat_ref))

    def sender_of(self, *, bot: str, chat_id: int, message_id: int) -> str | None:
        """The profile that sent this message, or ``None`` if we did not."""
        return self._entries.get((bot, chat_id, message_id))

    def forget(self, *, bot: str, chat_id: int, message_id: int) -> None:
        self._entries.pop((bot, chat_id, message_id), None)

    def __len__(self) -> int:
        return len(self._entries)


class TelegramService:
    """One connector for every configured bot.

    Args:
        settings: the validated ``telegram:`` section.
        api: the Bot API seam (:class:`palaia_hub.telegram.api.BotApi`).
        secrets: the encrypted secret store, read-only, per call.
        messenger: backs ``kind: messenger`` routes. ``None`` — such a route
            is refused at delivery with a message naming the omission, rather
            than dropping the traffic quietly.
        vaults: registered vault key → :class:`InboxSink`, backing
            ``kind: inbox`` routes. Same contract.
        publish: the hub's event hook
            (:data:`palaia_hub.events.schema.HubEventHook`). ``None`` in
            tests and in a hub with no bus; the connector works either way.
        ledger_capacity: see :class:`SentLedger`.
    """

    def __init__(
        self,
        settings: TelegramSettings,
        api: BotApi,
        secrets: SecretReader,
        *,
        messenger: MessengerSink | None = None,
        vaults: Mapping[str, InboxSink] | None = None,
        publish: Any = None,
        ledger_capacity: int = DEFAULT_SENT_LEDGER_SIZE,
        now: Any = time.time,
    ) -> None:
        self.settings = settings
        self._api = api
        self._secrets = secrets
        self._messenger = messenger
        self._vaults = dict(vaults or {})
        self.publish = publish
        self._routes = RoutingTable(settings.routes)
        self._ledger = SentLedger(ledger_capacity)
        self._now = now

    # ---------------------------------------------------------------- config

    @property
    def routes(self) -> RoutingTable:
        return self._routes

    @property
    def ledger(self) -> SentLedger:
        return self._ledger

    @property
    def has_messenger(self) -> bool:
        """Whether a ``kind: messenger`` route has anything to deliver to.

        Read by :class:`palaia_hub.telegram.runtime.TelegramRuntime`'s
        startup check, which warns about a route that would be refused at
        delivery rather than waiting for the first message to find out.
        """
        return self._messenger is not None

    @property
    def vault_keys(self) -> frozenset[str]:
        """The vault keys a ``kind: inbox`` route can land in — the map this
        service was built with, which is fixed for the life of the process
        (a vault created later is reachable after a restart)."""
        return frozenset(self._vaults)

    def enabled_bots(self) -> list[TelegramBotConfig]:
        """Every configured bot that is switched on."""
        return [bot for bot in self.settings.bots if bot.enabled]

    def polling_bots(self) -> list[TelegramBotConfig]:
        """The bots the long poller is responsible for."""
        return [bot for bot in self.enabled_bots() if bot.transport == "polling"]

    def require_bot(self, key: str) -> TelegramBotConfig:
        """The enabled bot under ``key``.

        Raises:
            UnknownBotError: no such bot, or it is switched off. The two are
                one error on purpose — "bot 'support' is not available" is
                the same thing from the caller's side, and distinguishing
                them would tell an unauthorised caller which bot keys exist.
        """
        bot = self.settings.bot(key)
        if bot is None or not bot.enabled:
            available = sorted(b.key for b in self.enabled_bots())
            raise UnknownBotError(
                f"no Telegram bot named {key!r} is available. Fix: use one of "
                f"{available or ['(none configured)']} — the bot key is the hub's "
                "own name for it (telegram.bots[].key in config.yaml), not the "
                "bot's Telegram username."
            )
        return bot

    def _token(self, bot: TelegramBotConfig) -> str:
        """This bot's token, for the duration of one call. Never stored."""
        value = (self._secrets.get(bot.token_secret) or "").strip()
        if not value:
            raise MissingSecretError(
                f"Telegram bot {bot.key!r} names the secret "
                f"{bot.token_secret!r}, and the secret store holds nothing under "
                "that name. Fix: store the bot token with "
                f"`PUT /api/secrets/{bot.token_secret}`. The token never goes in "
                "config.yaml."
            )
        return value

    def webhook_secret(self, bot: TelegramBotConfig) -> str:
        """The value Telegram must echo in its secret-token header.

        Raises:
            MissingSecretError: the bot is in webhook mode and the named
                secret is empty. Refusing here is what stops the endpoint
                from degrading into "no check at all" the moment an
                operator forgets to store the value.
        """
        if not bot.webhook_secret:
            raise MissingSecretError(
                f"Telegram bot {bot.key!r} is not in webhook mode, so it has no "
                "webhook secret."
            )
        value = (self._secrets.get(bot.webhook_secret) or "").strip()
        if not value:
            raise MissingSecretError(
                f"Telegram bot {bot.key!r} names the webhook secret "
                f"{bot.webhook_secret!r}, and the secret store holds nothing "
                f"under that name. Fix: store it with "
                f"`PUT /api/secrets/{bot.webhook_secret}` and pass the same value "
                "as `secret_token` to Telegram's setWebhook."
            )
        return value

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self.publish is None:
            return
        try:
            self.publish(event, data)
        except Exception:  # pragma: no cover - a bus fault must not eat traffic
            logger.warning("telegram event %s could not be published", event, exc_info=True)

    # --------------------------------------------------------------- inbound

    async def fetch_updates(
        self, bot_key: str, *, offset: int | None, timeout: float | None = None
    ) -> list[dict[str, Any]]:
        """One ``getUpdates`` batch for ``bot_key``, raw.

        The poller's whole reason to exist inside this package: it needs the
        bot's token, and the token stays here. Returning raw updates rather
        than normalised ones is deliberate — the poller advances its offset
        from ``update_id``, which survives an update shape nothing else
        understands.
        """
        bot = self.require_bot(bot_key)
        token = self._token(bot)
        return await self._api.get_updates(
            token,
            offset=offset,
            timeout=timeout if timeout is not None else self.settings.poll_timeout_seconds,
            allowed_updates=ALLOWED_UPDATES,
        )

    async def handle_update(self, bot_key: str, update: dict[str, Any]) -> DispatchOutcome:
        """Normalise, route and deliver one raw update. Never raises.

        The contract the poller depends on: whatever happens — an unknown
        update shape, a destination that is not wired, a vault that refuses
        the capture — this returns an outcome and the caller advances past
        the update. A connector that could be wedged by one bad message is a
        connector that stops delivering the next thousand good ones.
        """
        message = normalise_update(bot_key, update)
        if message is None:
            return DispatchOutcome(
                bot=bot_key, detail="update carried no message payload; ignored"
            )

        self._emit(EVENT_RECEIVED, message.metadata())

        route = self._routes.resolve(message)
        if route is None:
            keys = self._routes.candidates(
                chat_id=message.chat_ref, chat_username=message.chat_username
            )
            detail = (
                f"no route claims {bot_key}/{message.chat_ref}. Fix: add a "
                f"telegram.routes entry with bot: {bot_key} and one of "
                f"chat: {', '.join(repr(k) for k in keys)}."
            )
            self._emit(EVENT_DROPPED, {**message.metadata(), "candidates": keys})
            logger.info(
                "telegram message %d from chat %s (bot %r) matched no route",
                message.message_id,
                message.chat_ref,
                bot_key,
            )
            return DispatchOutcome(bot=bot_key, message=message, routed=False, detail=detail)

        try:
            detail = await self._dispatch(message, route.destination)
        except Exception as exc:  # a destination's own failure, not the hub's
            logger.warning(
                "telegram message %d (bot %r) could not be delivered to %s: %s",
                message.message_id,
                bot_key,
                route.destination.describe(),
                exc,
            )
            return DispatchOutcome(
                bot=bot_key,
                message=message,
                routed=True,
                destination=route.destination.describe(),
                delivered=False,
                detail=f"delivery to {route.destination.describe()} failed: {exc}",
            )
        return DispatchOutcome(
            bot=bot_key,
            message=message,
            routed=True,
            destination=route.destination.describe(),
            delivered=True,
            detail=detail,
        )

    async def _dispatch(self, message: InboundMessage, destination: TelegramDestination) -> str:
        if destination.kind == "messenger":
            return await self._dispatch_messenger(message, destination)
        if destination.kind == "inbox":
            return await self._dispatch_inbox(message, destination)
        return self._dispatch_event(message, destination)

    def _subject(self, message: InboundMessage) -> str:
        first_line = (message.text.splitlines() or [""])[0].strip()
        if len(first_line) > SUBJECT_PREVIEW_CHARS:
            first_line = first_line[: SUBJECT_PREVIEW_CHARS - 1].rstrip() + "…"
        head = f"Telegram {message.bot}/{message.chat_label}"
        return f"{head}: {first_line}" if first_line else f"{head}: (no text)"

    def _body(self, message: InboundMessage) -> str:
        """The envelope body: who said it, what they said, what they attached.

        Clipped to :data:`~palaia_hub.messenger.models.MAX_BODY_BYTES` with a
        marker naming what was cut. The messenger's own rule is *refuse, do
        not truncate* — right for an agent, which can go write the long thing
        to memory instead, and wrong here: the sender is a human on a phone
        who is never going to be told their message was refused for being 20
        bytes over. A clipped relay with the cut stated beats a message that
        never arrives, and the full text is still in the Telegram chat it
        came from.
        """
        header = f"From {message.sender_label} in {message.chat_label} (message "
        header += f"{message.message_id}{', edited' if message.edited else ''})"
        parts = [header, "", message.text or "(no text)"]
        if message.attachments:
            listed = ", ".join(
                f"{a.kind}:{a.file_id}" + (f" ({a.file_name})" if a.file_name else "")
                for a in message.attachments
            )
            parts += ["", f"Attachments (references only): {listed}"]
        body = "\n".join(parts)
        encoded = body.encode("utf-8")
        if len(encoded) <= MAX_BODY_BYTES:
            return body
        marker = f"\n… [clipped: {len(encoded)} bytes of Telegram message]"
        room = MAX_BODY_BYTES - len(marker.encode("utf-8"))
        return encoded[:room].decode("utf-8", errors="ignore") + marker

    async def _dispatch_messenger(
        self, message: InboundMessage, destination: TelegramDestination
    ) -> str:
        if self._messenger is None:
            raise RuntimeError(
                "this hub has no messenger, so a `kind: messenger` route cannot "
                "deliver. Fix: route to `kind: inbox` or `kind: event` instead."
            )
        await self._messenger.send_as_owner(
            message_type=destination.message_type,
            to=destination.to or "",
            subject=self._subject(message),
            body=self._body(message),
            urgency=destination.urgency,
            expects_reply=False,
        )
        return f"relayed to messenger recipient {destination.to!r} as the owner"

    async def _dispatch_inbox(
        self, message: InboundMessage, destination: TelegramDestination
    ) -> str:
        vault_key = destination.vault or ""
        sink = self._vaults.get(vault_key)
        if sink is None:
            raise RuntimeError(
                f"vault {vault_key!r} is not registered on this hub, so a "
                f"`kind: inbox` route pointing at it cannot deliver "
                f"(registered: {sorted(self._vaults) or 'none'})."
            )
        await sink.capture(
            what_it_concerns=f"Telegram {message.bot}/{message.chat_label}",
            why_keep=(
                f"Arrived through the {message.bot!r} Telegram bot and was routed "
                "to this vault's inbox for curation."
            ),
            content=self._body(message),
            source=f"telegram:{message.bot}/{message.chat_ref}#{message.message_id}",
        )
        return f"captured into vault {vault_key!r} inbox/"

    def _dispatch_event(self, message: InboundMessage, destination: TelegramDestination) -> str:
        """Put the message on the hub's event bus — **text included**.

        The one place this connector does that, and only because the operator
        wrote the route. It is how a Telegram message triggers an automation
        (the dispatcher subscribes to this same bus), and it is stated
        plainly in ``v3/docs/telegram.md``: an ``event`` route puts the words
        a human typed onto every SSE listener and every outbound webhook this
        hub is configured with. The metadata-only
        :data:`EVENT_RECEIVED` fired just before is what an operator who does
        not want that should route on instead.
        """
        label = destination.label or f"{message.bot}/{message.chat_ref}"
        self._emit(
            EVENT_ROUTED,
            {**message.metadata(), "label": label, "text": message.text},
        )
        return f"published {EVENT_ROUTED} (label {label!r}) — text included, by route"

    # -------------------------------------------------------------- outbound

    def _check_grant(self, profile: str, bot: str, chat: str) -> None:
        grant = self.settings.grant(profile)
        if grant is None:
            raise NotPermittedError(
                f"MCP profile {profile!r} may not send Telegram messages: no "
                "telegram.grants entry names it. Fix: add one naming the bots "
                "and chats this profile may address — there is no implicit "
                "permission for an unlisted profile."
            )
        if not grant.allows(bot, chat):
            raise NotPermittedError(
                f"MCP profile {profile!r} may not send to {chat} through bot "
                f"{bot!r}. Its grant covers bots {grant.bots} and chats "
                f"{grant.chats}."
            )

    @staticmethod
    def _check_text(text: str) -> str:
        body = text.strip()
        if not body:
            raise MessageTooLongError(
                "the message is empty. Fix: Telegram refuses an empty message; "
                "send something, or do not call the tool."
            )
        if len(body) > MAX_MESSAGE_CHARS:
            raise MessageTooLongError(
                f"the message is {len(body)} characters; Telegram's hard limit is "
                f"{MAX_MESSAGE_CHARS}. Fix: send it in parts, or put the long "
                "content in memory and send a short pointer."
            )
        return body

    async def send(
        self,
        *,
        profile: str,
        bot: str,
        chat: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> SentMessage:
        """Send ``text`` to ``chat`` through ``bot``, as ``profile``.

        ``reply_to_message_id`` is what makes ``telegram_reply`` a thread and
        not just another message in the room — Telegram shows it quoted under
        the original.
        """
        config = self.require_bot(bot)
        chat_ref = normalise_chat_ref(chat)
        self._check_grant(profile, bot, chat_ref)
        body = self._check_text(text)
        token = self._token(config)
        raw = await self._api.send_message(
            token, chat_id=chat_ref, text=body, reply_to_message_id=reply_to_message_id
        )
        sent = _sent_from(bot, raw, chat_ref, reply_to_message_id, len(body))
        self._ledger.record(
            bot=bot,
            chat_id=sent.chat_id,
            message_id=sent.message_id,
            profile=profile,
            alias=None if chat_ref.lstrip("-").isdigit() else chat_ref,
        )
        self._emit(
            EVENT_SENT,
            {
                "bot": bot,
                "chat_id": sent.chat_id,
                "message_id": sent.message_id,
                "reply_to_message_id": reply_to_message_id,
                "text_chars": sent.text_chars,
                "profile": profile,
            },
        )
        logger.info(
            "telegram: profile %r sent message %d to chat %s via bot %r",
            profile,
            sent.message_id,
            sent.chat_id,
            bot,
        )
        return sent

    def _chat_id(self, bot: str, chat_ref: str) -> int:
        """``chat_ref`` as the numeric id edit/delete are keyed by.

        A send addressed to ``@name`` teaches the ledger which id that name
        is; before any such send, a ``@name`` cannot be resolved without a
        Bot API round trip that would tell us nothing we are allowed to act
        on anyway (a message we did not send is not ours to edit).
        """
        chat_id = self._ledger.chat_id_for(bot=bot, chat_ref=chat_ref)
        if chat_id is None:
            raise NotOurMessageError(
                f"this hub has not sent anything to {chat_ref} through bot "
                f"{bot!r}, so there is no message of ours there to edit or "
                "delete. Fix: pass the numeric chat_id that telegram_send "
                "returned."
            )
        return chat_id

    def _require_ours(self, *, profile: str, bot: str, chat_id: int, message_id: int) -> None:
        sender = self._ledger.sender_of(bot=bot, chat_id=chat_id, message_id=message_id)
        if sender is None:
            raise NotOurMessageError(
                f"message {message_id} in chat {chat_id} is not one this hub sent "
                f"through bot {bot!r} in this process, so it cannot be edited or "
                "deleted here. Editing someone else's message is group "
                "moderation, which this connector does not do; a message sent "
                "before the last hub restart is simply no longer tracked."
            )
        if sender != profile:
            raise NotPermittedError(
                f"message {message_id} in chat {chat_id} was sent by MCP profile "
                f"{sender!r}, not {profile!r}. A profile edits and deletes its "
                "own messages only."
            )

    async def edit(
        self, *, profile: str, bot: str, chat: str, message_id: int, text: str
    ) -> SentMessage:
        """Replace the text of a message this profile sent."""
        config = self.require_bot(bot)
        chat_ref = normalise_chat_ref(chat)
        self._check_grant(profile, bot, chat_ref)
        body = self._check_text(text)
        self._require_ours(
            profile=profile,
            bot=bot,
            chat_id=self._chat_id(bot, chat_ref),
            message_id=message_id,
        )
        token = self._token(config)
        raw = await self._api.edit_message_text(
            token, chat_id=chat_ref, message_id=message_id, text=body
        )
        return _sent_from(bot, raw, chat_ref, None, len(body))

    async def delete(
        self, *, profile: str, bot: str, chat: str, message_id: int
    ) -> DeletedMessage:
        """Delete a message this profile sent."""
        config = self.require_bot(bot)
        chat_ref = normalise_chat_ref(chat)
        self._check_grant(profile, bot, chat_ref)
        chat_id = self._chat_id(bot, chat_ref)
        self._require_ours(profile=profile, bot=bot, chat_id=chat_id, message_id=message_id)
        token = self._token(config)
        deleted = await self._api.delete_message(
            token, chat_id=chat_ref, message_id=message_id
        )
        if deleted:
            self._ledger.forget(bot=bot, chat_id=chat_id, message_id=message_id)
        return DeletedMessage(
            bot=bot, chat_id=chat_id, message_id=message_id, deleted=bool(deleted)
        )

    def list_chats(self, profile: str) -> list[ChatInfo]:
        """Every ``(bot, chat)`` this profile can see, and whether it may send.

        Built from configuration alone — Telegram has no "list my chats"
        method, and what an agent actually needs to know is what the *hub*
        permits, which is a hub-side fact.
        """
        grant = self.settings.grant(profile)
        rows: list[ChatInfo] = []
        seen: set[tuple[str, str]] = set()
        for bot in self.enabled_bots():
            for route in self._routes.for_bot(bot.key):
                seen.add((bot.key, route.chat))
                rows.append(
                    ChatInfo(
                        bot=bot.key,
                        chat=route.chat,
                        destination=route.destination.describe(),
                        can_send=bool(grant and grant.allows(bot.key, route.chat)),
                    )
                )
            if grant is None:
                continue
            for chat in grant.chats:
                if (bot.key, chat) in seen or not grant.allows(bot.key, chat):
                    continue
                seen.add((bot.key, chat))
                rows.append(ChatInfo(bot=bot.key, chat=chat, destination=None, can_send=True))
        return rows

    async def check_bot(self, key: str) -> dict[str, Any]:
        """Probe one bot's connection: ``getMe``, reported without its token.

        The dashboard's per-bot "connection state" reads this. Returns the
        two fields worth showing (``id``, ``username``) rather than passing
        Telegram's whole user object through, so a future field Telegram adds
        cannot surprise a surface that renders it.
        """
        bot = self.require_bot(key)
        token = self._token(bot)
        me = await self._api.get_me(token)
        return {
            "bot": key,
            "telegram_id": me.get("id"),
            "username": me.get("username"),
            "transport": bot.transport,
        }

    @property
    def allowed_updates(self) -> tuple[str, ...]:
        return ALLOWED_UPDATES


def _sent_from(
    bot: str,
    raw: dict[str, Any],
    chat_ref: str,
    reply_to_message_id: int | None,
    text_chars: int,
) -> SentMessage:
    """The API's message object as our own result shape.

    ``chat_ref`` is the fallback for ``chat.id`` because a send addressed to
    ``@name`` still comes back with the numeric id — but a self-hosted Bot
    API server that omitted it should not crash the call.
    """
    chat = raw.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, int):
        chat_id = int(chat_ref) if chat_ref.lstrip("-").isdigit() else 0
    message_id = raw.get("message_id")
    return SentMessage(
        bot=bot,
        chat_id=chat_id,
        message_id=message_id if isinstance(message_id, int) else 0,
        reply_to_message_id=reply_to_message_id,
        text_chars=text_chars,
    )


__all__ = [
    "EVENT_DROPPED",
    "EVENT_RECEIVED",
    "EVENT_ROUTED",
    "EVENT_SENT",
    "InboxSink",
    "MessengerSink",
    "SecretReader",
    "SentLedger",
    "TelegramService",
]
