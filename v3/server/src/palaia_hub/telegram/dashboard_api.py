"""The dashboard's Telegram panel (issue #439): ``/api/telegram``.

Two routes, owner-only like everything under ``/api/`` (the admin session
gate and its CSRF check cover them with no code here —
:mod:`palaia_hub.admin_session`):

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

from typing import Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .models import (
    BotCheck,
    RecentMessage,
    TelegramBotConfig,
    TransportKind,
    UnknownBotError,
)
from .runtime import TelegramRuntime

#: Where the panel's routes live. A module constant, like
#: :data:`~palaia_hub.telegram.webhook.WEBHOOK_PREFIX`, so the threat
#: model's route scan finds the group by its literal.
DASHBOARD_PREFIX = "/api/telegram"


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
    transport: TransportKind
    enabled: bool
    #: Whether the secret store holds the bot's token. ``False`` is the
    #: day-one failure: the bot is in ``config.yaml``, its token is not.
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


class TelegramStatus(BaseModel):
    """``GET /api/telegram/status``."""

    model_config = ConfigDict(extra="forbid")

    bots: list[BotStatus]
    routes: list[RouteStatus]
    #: Newest first; see :class:`~palaia_hub.telegram.models.RecentMessage`.
    recent: list[RecentMessage]


def build_telegram_dashboard_router(runtime: TelegramRuntime, secrets: SecretPresence) -> APIRouter:
    """The panel's two routes over ``runtime``.

    Args:
        runtime: the running connector — its service's configuration and
            recorded outcomes, its pollers' state, its cached checks.
        secrets: the secret store the connector reads its tokens from,
            asked only whether a name is stored.
    """
    router = APIRouter(prefix=DASHBOARD_PREFIX, tags=["telegram"])
    service = runtime.service

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
        return BotStatus(
            key=bot.key,
            label=bot.label or bot.key,
            transport=bot.transport,
            enabled=bot.enabled,
            token_stored=secrets.has(bot.token_secret),
            webhook_secret_stored=(secrets.has(bot.webhook_secret) if bot.webhook_secret else None),
            polling=_polling(bot.key),
            last_update_at=service.last_update_at(bot.key),
            last_check=runtime.last_checks.get(bot.key),
        )

    @router.get("/status", response_model=TelegramStatus)
    async def telegram_status() -> TelegramStatus:
        """Everything the panel shows, from memory — no Bot API call."""
        return TelegramStatus(
            bots=[_bot(bot) for bot in service.settings.bots],
            routes=[
                RouteStatus(
                    bot=route.bot,
                    chat=route.chat,
                    kind=route.destination.kind,
                    destination=route.destination.describe(),
                )
                for route in service.routes.routes
            ],
            recent=service.recent_messages(),
        )

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

    return router


__all__ = [
    "DASHBOARD_PREFIX",
    "BotStatus",
    "PollingState",
    "RouteStatus",
    "SecretPresence",
    "TelegramStatus",
    "build_telegram_dashboard_router",
]
