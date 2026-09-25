"""The dashboard's Telegram panel (issues #439, #463): ``/api/telegram``.

Owner-only like everything under ``/api/`` (the admin session gate and its
CSRF check cover every route here with no code of their own —
:mod:`palaia_hub.admin_session`). Two reads and one probe:

* ``GET /api/telegram/status`` — per bot, whether it is set up and
  connected, when it last received something and its last error; the
  routing table; and what happened to the last messages. **It never calls
  Telegram**: the panel refetches it on every ``telegram.*`` event, and a
  read that reached out to the Bot API each time would turn a busy group
  into a request storm against it.
* ``POST /api/telegram/bots/{key}/check`` — the one outbound call the panel
  can cause: ``getMe`` for one bot, on the operator's click, cached on
  :class:`~palaia_hub.telegram.runtime.TelegramRuntime` so the next status
  read shows it. The same split ``/api/gateway/upstreams`` makes between its
  listing and its ``/probe``.

**The editor** (issue #463): add, change and remove bots
(``/bots``), routing rules (``/routes``) and outbound grants (``/grants``)
— MASTERPLAN P7's "no config-file editing as a required path". Every write
does the same four things, in order: build the edited ``telegram:``
section and validate it exactly as :class:`palaia_hub.config.HubConfig`
does at load time (the schema, then
:meth:`~palaia_hub.telegram.models.TelegramSettings.check_consistency` — a
route naming an unknown bot is refused here as it would be there); write it
back to ``config.yaml`` through the same section-replacing patch the
gateway editor uses (:func:`palaia_hub.modes.patch.replace_config_section`);
apply it to the running connector
(:meth:`~palaia_hub.telegram.runtime.TelegramRuntime.apply_settings` — no
restart); and publish ``telegram.config.updated``. Written before applied,
so a disk that refuses the write leaves the running hub as it was.

A bot's *token* is not part of any of this: the editor stores it through
the write-only ``PUT /api/secrets/<name>`` and only ever names it here
(``token_secret``). Every request model forbids unknown fields, so a
client that tried to send a token along with a bot is refused rather than
having it silently dropped — or written into ``config.yaml``.

**Metadata only, in memory.** This is ADR-006's "owner-facing view" and
nothing more: no message text is kept or served
(:class:`~palaia_hub.telegram.models.RecentMessage` has no field for it),
and everything shown is lost on restart. The panel is a dashboard screen,
not an MCP App — ADR-006 records that rule-8 answer.

**No credential in any response.** Whether a token is stored is a boolean
read through :meth:`palaia_hub.upstream.secrets.SecretStore.has`, which
never decrypts anything; no model below has a field a token, a webhook
secret or a secret's value could be placed in.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..gateway.config import CURATOR_PROFILE_PATH
from ..modes.patch import replace_config_section
from ..upstream.secrets import SecretStoreError, validate_secret_name
from .models import (
    CHAT_WILDCARD,
    BotCheck,
    RecentMessage,
    TelegramBotConfig,
    TelegramConfigError,
    TelegramDestination,
    TelegramGrant,
    TelegramRoute,
    TelegramSettings,
    TransportKind,
    UnknownBotError,
    normalise_chat_ref,
)
from .runtime import TelegramRuntime

#: Where the panel's routes live. A module constant, like
#: :data:`~palaia_hub.telegram.webhook.WEBHOOK_PREFIX`, so the threat
#: model's route scan finds the group by its literal.
DASHBOARD_PREFIX = "/api/telegram"

#: Published after every saved edit (issue #463). ``data`` says what kind
#: of thing changed and how — ``{"subject": "bot"|"route"|"grant",
#: "action": "created"|"updated"|"deleted", "key": ...}`` — naming a bot
#: key, a ``bot/chat`` pair or a profile path, never a secret's name.
EVENT_CONFIG_UPDATED = "telegram.config.updated"


def default_token_secret(key: str) -> str:
    """The secret name the editor files a new bot's token under when the
    operator names none: ``telegram_<key>``. A bot key is always a legal
    secret name's tail (lowercase letters, digits, ``_``, ``-``)."""
    return f"telegram_{key}"


def default_webhook_secret(key: str) -> str:
    """Same, for a webhook bot's echo secret: ``telegram_<key>_webhook``."""
    return f"telegram_{key}_webhook"


def render_telegram_section(settings: TelegramSettings) -> str:
    """The ``telegram:`` section body as ``config.yaml`` holds it —
    indented under the header, header excluded — the same shape
    :func:`palaia_hub.gateway.settings_bridge.render_gateway_section`
    renders for ``gateway:``. Defaults are left out, so a saved section
    reads like one an operator would write by hand: no ``enabled: true``,
    no ``urgency: normal`` on every rule — except the ones that say *who*:
    a rule always names its ``chat`` and a grant its ``bots`` and
    ``chats``, even when that is ``*``, because "every chat" is the most
    important thing to see about a rule, not a detail to infer from an
    absent line."""
    payload = settings.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    payload.setdefault("bots", [])
    if "routes" in payload:
        payload["routes"] = [
            {"bot": route.bot, "chat": route.chat, **dumped}
            for route, dumped in zip(settings.routes, payload["routes"], strict=True)
        ]
    if "grants" in payload:
        payload["grants"] = [
            {**dumped, "bots": list(grant.bots), "chats": list(grant.chats)}
            for grant, dumped in zip(settings.grants, payload["grants"], strict=True)
        ]
    dumped = yaml.safe_dump({"telegram": payload}, default_flow_style=False, sort_keys=False)
    _, _, body = dumped.partition("\n")
    if body and not body.endswith("\n"):
        body += "\n"
    return body


def persist_telegram_settings(path: Path, settings: TelegramSettings) -> None:
    """Write ``settings`` back as ``config.yaml``'s ``telegram:`` section,
    every other line — comments included — left as it was. Comments
    *inside* the section are not kept: it is written whole, the same
    contract the ``gateway:`` section has."""
    replace_config_section(path, "telegram", render_telegram_section(settings))


class SecretPresence(Protocol):
    """The one question this router asks of the secret store: *is there
    one?* — never *what is it*. :class:`~palaia_hub.upstream.secrets.
    SecretStore` satisfies it structurally."""

    def has(self, name: str) -> bool: ...


class PollingState(BaseModel):
    """A polling bot's poll loop, as the panel shows it."""

    model_config = ConfigDict(extra="forbid")

    #: Whether its poll task is alive right now.
    running: bool
    last_ok_at: float | None
    #: The last failure as one token-free line. Kept after a recovery.
    last_error: str | None
    last_error_at: float | None
    consecutive_failures: int


class BotStatus(BaseModel):
    """One configured bot — enabled or not — with no credential in sight."""

    model_config = ConfigDict(extra="forbid")

    key: str
    #: The configured ``label``, or the key when there is none.
    label: str
    #: The configured ``label`` itself — ``None`` when there is none — so
    #: the editor can tell "no label" from "labelled with its key".
    configured_label: str | None
    transport: TransportKind
    enabled: bool
    #: The *name* the bot's token is filed under in the secret store — where
    #: the editor stores it (``PUT /api/secrets/<name>``). Never the token:
    #: the name is what ``config.yaml`` holds in plain text anyway.
    token_secret: str
    #: Webhook bots only: the name of the secret Telegram must echo.
    webhook_secret: str | None
    #: Whether the secret store holds the bot's token. ``False`` is the
    #: day-one failure: the bot is configured, its token is not stored.
    token_stored: bool
    #: Webhook bots only: whether the secret Telegram must echo is stored.
    webhook_secret_stored: bool | None
    #: ``None`` for a webhook bot or a switched-off one — no poll loop.
    polling: PollingState | None
    #: When it last received a message (hub clock), since the hub started.
    last_update_at: float | None
    #: The last "Check connection", or ``None`` if nobody has asked yet.
    last_check: BotCheck | None


class RouteStatus(BaseModel):
    """One ``(bot, chat) → destination`` rule."""

    model_config = ConfigDict(extra="forbid")

    bot: str
    #: A numeric chat id, a public ``@name``, or ``*`` for every chat.
    chat: str
    kind: str
    #: :meth:`~palaia_hub.telegram.models.TelegramDestination.describe`.
    destination: str
    #: The destination as configured, for the editor to start from.
    target: TelegramDestination


class TelegramStatus(BaseModel):
    """``GET /api/telegram/status`` — and the answer to every edit."""

    model_config = ConfigDict(extra="forbid")

    bots: list[BotStatus]
    routes: list[RouteStatus]
    #: The outbound fence, as configured (default-deny: a profile with no
    #: entry sends nothing).
    grants: list[TelegramGrant]
    #: Newest first; see :class:`~palaia_hub.telegram.models.RecentMessage`.
    recent: list[RecentMessage]
    #: The vault keys a ``kind: inbox`` rule can deliver into right now.
    vaults: list[str]
    #: Whether a ``kind: messenger`` rule has a messenger to deliver to.
    messenger: bool
    #: Rules and bots the configuration accepts but this running hub cannot
    #: serve — :meth:`~palaia_hub.telegram.runtime.TelegramRuntime.
    #: startup_warnings`, the same lines the log carries.
    warnings: list[str]
    #: Whether this panel can save edits (``False`` only for a hub built
    #: without a ``config.yaml`` to write them to).
    editable: bool


class BotCreate(BaseModel):
    """``POST /api/telegram/bots``. No field a token could travel in —
    ``extra="forbid"`` refuses one instead of dropping it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str | None = None
    transport: TransportKind = "polling"
    enabled: bool = True
    #: Defaults to :func:`default_token_secret`.
    token_secret: str | None = None
    #: A webhook bot's echo secret; defaults to
    #: :func:`default_webhook_secret` when the transport is ``webhook``.
    webhook_secret: str | None = None


class BotUpdate(BaseModel):
    """``PATCH /api/telegram/bots/{key}`` — every field optional, an omitted
    one keeps its value, and an explicit ``"label": null`` clears the label.
    The key itself is not editable: routes and grants address the bot by
    it, and so do agents' tool calls."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    transport: TransportKind | None = None
    enabled: bool | None = None
    token_secret: str | None = None
    webhook_secret: str | None = None


class GrantUpdate(BaseModel):
    """``PUT /api/telegram/grants/{profile}``: the bots and chats this profile
    may send to. ``*`` means every one; an empty list means none."""

    model_config = ConfigDict(extra="forbid")

    bots: list[str] = [CHAT_WILDCARD]
    chats: list[str] = [CHAT_WILDCARD]


def build_telegram_dashboard_router(
    runtime: TelegramRuntime,
    secrets: SecretPresence,
    *,
    config_path: Path | None = None,
    publish: Callable[[str, dict[str, Any]], None] | None = None,
) -> APIRouter:
    """The panel's routes over ``runtime``.

    Args:
        runtime: the running connector — its service's configuration and
            recorded outcomes, its pollers' state, its cached checks; and
            what every edit is applied to.
        secrets: the secret store the connector reads its tokens from,
            asked only whether a name is stored.
        config_path: the hub's ``config.yaml``, where an edit is written
            back. ``None`` mounts the panel read-only — no editing route
            exists at all, rather than one that applies an edit the next
            restart would silently revert.
        publish: called with :data:`EVENT_CONFIG_UPDATED` after each saved
            edit. ``None`` in tests; the edit works either way.
    """
    router = APIRouter(prefix=DASHBOARD_PREFIX, tags=["telegram"])
    service = runtime.service
    # One edit at a time: each is read-modify-write of the whole section.
    lock = asyncio.Lock()

    def _polling(key: str) -> PollingState | None:
        poller = runtime.pollers.get(key)
        if poller is None:
            return None
        task = runtime.tasks.get(key)
        return PollingState(
            running=task is not None and not task.done(),
            last_ok_at=poller.last_ok_at,
            last_error=poller.last_error,
            last_error_at=poller.last_error_at,
            consecutive_failures=poller.consecutive_failures,
        )

    def _bot(bot: TelegramBotConfig) -> BotStatus:
        webhook = bot.transport == "webhook" and bot.webhook_secret is not None
        return BotStatus(
            key=bot.key,
            label=bot.label or bot.key,
            configured_label=bot.label,
            transport=bot.transport,
            enabled=bot.enabled,
            token_secret=bot.token_secret,
            webhook_secret=bot.webhook_secret if webhook else None,
            token_stored=secrets.has(bot.token_secret),
            webhook_secret_stored=(
                secrets.has(bot.webhook_secret)
                if webhook and bot.webhook_secret is not None
                else None
            ),
            polling=_polling(bot.key),
            last_update_at=service.last_update_at(bot.key),
            last_check=runtime.last_checks.get(bot.key),
        )

    def _status(warnings: list[str] | None = None) -> TelegramStatus:
        settings = service.settings
        return TelegramStatus(
            bots=[_bot(bot) for bot in settings.bots],
            routes=[
                RouteStatus(
                    bot=route.bot,
                    chat=route.chat,
                    kind=route.destination.kind,
                    destination=route.destination.describe(),
                    target=route.destination,
                )
                for route in service.routes.routes
            ],
            grants=list(settings.grants),
            recent=service.recent_messages(),
            vaults=sorted(service.vault_keys),
            messenger=service.has_messenger,
            warnings=warnings if warnings is not None else runtime.startup_warnings(),
            editable=config_path is not None,
        )

    @router.get("/status", response_model=TelegramStatus)
    async def telegram_status() -> TelegramStatus:
        """Everything the panel shows, from memory — no Bot API call."""
        return _status()

    @router.post("/bots/{key}/check", response_model=BotStatus)
    async def check_telegram_bot(key: str) -> BotStatus:
        """``getMe`` now, for one bot. A refused token is a ``200`` whose
        ``last_check.ok`` is false — the check worked, the bot does not."""
        try:
            await runtime.check_bot(key)
        except UnknownBotError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        config = service.settings.bot(key)
        assert config is not None  # check_bot just resolved it
        return _bot(config)

    if config_path is None:
        return router
    path = config_path

    def _dump() -> dict[str, Any]:
        return service.settings.model_dump(mode="json")

    async def _save(
        edited: dict[str, Any], *, subject: str, action: str, key: str
    ) -> TelegramStatus:
        """Validate ``edited`` as ``config.yaml`` would, write it, run it.

        Raises:
            HTTPException: ``400`` naming the problem — the schema's own
                message, or the dangling cross-reference.
        """
        try:
            settings = TelegramSettings.model_validate(edited)
            settings.check_consistency()
            # A name the secret store would refuse is a token that can never
            # be stored — refused here, not at the first `PUT /api/secrets`.
            for bot in settings.bots:
                for name in (bot.token_secret, bot.webhook_secret):
                    if name is not None:
                        validate_secret_name(name)
        except (ValidationError, TelegramConfigError, SecretStoreError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_one_line(exc)) from exc
        persist_telegram_settings(path, settings)
        warnings = await runtime.apply_settings(settings)
        if publish is not None:
            publish(EVENT_CONFIG_UPDATED, {"subject": subject, "action": action, "key": key})
        return _status(warnings)

    def _bot_index(bots: list[dict[str, Any]], key: str) -> int:
        for index, bot in enumerate(bots):
            if bot["key"] == key:
                return index
        raise HTTPException(status_code=404, detail=f"no Telegram bot is configured as {key!r}")

    def _route_key(bot: str, chat: str) -> tuple[str, str]:
        try:
            return bot, normalise_chat_ref(chat)
        except TelegramConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _route_index(routes: list[dict[str, Any]], bot: str, chat: str) -> int:
        wanted = _route_key(bot, chat)
        for index, route in enumerate(routes):
            if (route["bot"], route["chat"]) == wanted:
                return index
        raise HTTPException(
            status_code=404, detail=f"no Telegram rule is configured for {bot}/{chat}"
        )

    # ------------------------------------------------------------------ bots

    @router.post("/bots", response_model=TelegramStatus)
    async def create_telegram_bot(body: BotCreate) -> TelegramStatus:
        """Add a bot. Its token is stored separately, by name."""
        async with lock:
            edited = _dump()
            if any(bot["key"] == body.key for bot in edited["bots"]):
                raise HTTPException(
                    status_code=409,
                    detail=f"a Telegram bot is already configured as {body.key!r}. "
                    "Fix: edit that one, or choose another key.",
                )
            webhook_secret = body.webhook_secret
            if body.transport == "webhook" and not webhook_secret:
                webhook_secret = default_webhook_secret(body.key)
            edited["bots"].append(
                {
                    "key": body.key,
                    "label": body.label or None,
                    "transport": body.transport,
                    "enabled": body.enabled,
                    "token_secret": body.token_secret or default_token_secret(body.key),
                    "webhook_secret": webhook_secret,
                }
            )
            return await _save(edited, subject="bot", action="created", key=body.key)

    @router.patch("/bots/{key}", response_model=TelegramStatus)
    async def update_telegram_bot(key: str, body: BotUpdate) -> TelegramStatus:
        async with lock:
            edited = _dump()
            bot = edited["bots"][_bot_index(edited["bots"], key)]
            if "label" in body.model_fields_set:
                bot["label"] = body.label or None
            if body.enabled is not None:
                bot["enabled"] = body.enabled
            if body.token_secret:
                bot["token_secret"] = body.token_secret
            if body.transport is not None:
                bot["transport"] = body.transport
            if body.webhook_secret:
                bot["webhook_secret"] = body.webhook_secret
            if bot["transport"] == "webhook" and not bot.get("webhook_secret"):
                bot["webhook_secret"] = default_webhook_secret(key)
            if bot["transport"] == "polling":
                # A polling bot has no echo secret; keeping a stale name
                # would only show up as "cannot receive yet" in the panel.
                bot["webhook_secret"] = None
            return await _save(edited, subject="bot", action="updated", key=key)

    @router.delete("/bots/{key}", response_model=TelegramStatus)
    async def delete_telegram_bot(key: str) -> TelegramStatus:
        """Remove a bot. Refused while a rule or a grant still names it —
        removing those is a decision about where messages go, and the
        operator makes it, not a cascade. Its stored token is left in the
        secret store."""
        async with lock:
            edited = _dump()
            index = _bot_index(edited["bots"], key)
            rules = [f"{r['bot']}/{r['chat']}" for r in edited["routes"] if r["bot"] == key]
            grants = [g["profile"] for g in edited["grants"] if key in g["bots"]]
            if rules or grants:
                named = []
                if rules:
                    named.append(f"rule(s) {', '.join(rules)}")
                if grants:
                    named.append(f"the grant(s) of profile(s) {', '.join(grants)}")
                raise HTTPException(
                    status_code=409,
                    detail=f"Telegram bot {key!r} is still used by {' and '.join(named)}. "
                    "Fix: remove those first — or switch the bot off instead, which "
                    "keeps them.",
                )
            del edited["bots"][index]
            return await _save(edited, subject="bot", action="deleted", key=key)

    # ---------------------------------------------------------------- routes

    @router.post("/routes", response_model=TelegramStatus)
    async def create_telegram_route(body: TelegramRoute) -> TelegramStatus:
        """Add a rule. ``body`` is already a validated rule: its chat is
        normalised and its destination has the fields its kind needs."""
        async with lock:
            edited = _dump()
            if any((r["bot"], r["chat"]) == (body.bot, body.chat) for r in edited["routes"]):
                raise HTTPException(
                    status_code=409,
                    detail=f"a rule for {body.bot}/{body.chat} already exists; one chat "
                    "has one destination. Fix: edit that rule instead.",
                )
            edited["routes"].append(body.model_dump(mode="json"))
            return await _save(
                edited, subject="route", action="created", key=f"{body.bot}/{body.chat}"
            )

    @router.put("/routes/{bot}/{chat}", response_model=TelegramStatus)
    async def replace_telegram_route(bot: str, chat: str, body: TelegramRoute) -> TelegramStatus:
        """Replace one rule — its bot and chat may change too."""
        async with lock:
            edited = _dump()
            index = _route_index(edited["routes"], bot, chat)
            clash = any(
                (r["bot"], r["chat"]) == (body.bot, body.chat)
                for i, r in enumerate(edited["routes"])
                if i != index
            )
            if clash:
                raise HTTPException(
                    status_code=409,
                    detail=f"a rule for {body.bot}/{body.chat} already exists. "
                    "Fix: edit or remove that rule first.",
                )
            edited["routes"][index] = body.model_dump(mode="json")
            return await _save(
                edited, subject="route", action="updated", key=f"{body.bot}/{body.chat}"
            )

    @router.delete("/routes/{bot}/{chat}", response_model=TelegramStatus)
    async def delete_telegram_route(bot: str, chat: str) -> TelegramStatus:
        async with lock:
            edited = _dump()
            index = _route_index(edited["routes"], bot, chat)
            removed = edited["routes"].pop(index)
            return await _save(
                edited,
                subject="route",
                action="deleted",
                key=f"{removed['bot']}/{removed['chat']}",
            )

    # ---------------------------------------------------------------- grants

    @router.put("/grants/{profile}", response_model=TelegramStatus)
    async def put_telegram_grant(profile: str, body: GrantUpdate) -> TelegramStatus:
        """Say which bots and chats one MCP profile may send to.

        The curator is refused: its profile never carries the Telegram
        tools (``ProfileConfig`` refuses the flag), so a grant for it could
        only ever be a mistake waiting for that fence to move. A profile
        path that does not exist (yet) is accepted — a grant can be written
        ahead of the profile, the same pre-declaration ``gateway:`` allows
        for a vault.
        """
        if profile == CURATOR_PROFILE_PATH:
            raise HTTPException(
                status_code=400,
                detail="the curator profile can never send to Telegram, so it "
                "takes no grant. Fix: grant a profile your agents connect with.",
            )
        async with lock:
            edited = _dump()
            grant = {"profile": profile, "bots": body.bots, "chats": body.chats}
            existing = [i for i, g in enumerate(edited["grants"]) if g["profile"] == profile]
            if existing:
                edited["grants"][existing[0]] = grant
                action = "updated"
            else:
                edited["grants"].append(grant)
                action = "created"
            return await _save(edited, subject="grant", action=action, key=profile)

    @router.delete("/grants/{profile}", response_model=TelegramStatus)
    async def delete_telegram_grant(profile: str) -> TelegramStatus:
        """Remove a profile's grant — which makes it default-deny again."""
        async with lock:
            edited = _dump()
            kept = [g for g in edited["grants"] if g["profile"] != profile]
            if len(kept) == len(edited["grants"]):
                raise HTTPException(
                    status_code=404, detail=f"profile {profile!r} has no Telegram grant"
                )
            edited["grants"] = kept
            return await _save(edited, subject="grant", action="deleted", key=profile)

    return router


def _one_line(exc: Exception) -> str:
    """A validation failure as the editor shows it: pydantic's messages
    without its URLs and input echoes, or the config error's own words."""
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors(include_url=False, include_input=False):
            where = ".".join(str(part) for part in error.get("loc", ()))
            message = str(error.get("msg", "")).removeprefix("Value error, ")
            parts.append(f"{where}: {message}" if where else message)
        return "; ".join(parts) or str(exc)
    return str(exc)


__all__ = [
    "DASHBOARD_PREFIX",
    "EVENT_CONFIG_UPDATED",
    "BotCreate",
    "BotStatus",
    "BotUpdate",
    "GrantUpdate",
    "PollingState",
    "RouteStatus",
    "SecretPresence",
    "TelegramStatus",
    "build_telegram_dashboard_router",
    "default_token_secret",
    "default_webhook_secret",
    "persist_telegram_settings",
    "render_telegram_section",
]
