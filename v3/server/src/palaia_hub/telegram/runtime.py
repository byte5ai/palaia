"""The Telegram connector's process lifecycle (issue #439): the poll tasks,
the Bot API client they share, and what the operator should hear at startup.

:class:`~palaia_hub.telegram.service.TelegramService`,
:class:`~palaia_hub.telegram.poller.LongPoller` and the webhook router were
built and tested in issue #411 and then never started: nothing in
:mod:`palaia_hub.serve` created a poll task, so a hub with a ``telegram:``
section received nothing. :class:`TelegramRuntime` is that missing piece,
and deliberately nothing more — the same shape
:class:`~palaia_hub.upstream.monitor.UpstreamHealthMonitor` has: built by
:func:`palaia_hub.serve.build_production_app`, started and stopped by the
app's own lifespan (:func:`palaia_hub.app.create_app`), and owning no logic
of its own beyond "one task per polling bot, and tear them down cleanly".

**One task per bot, not one loop over all of them**, for the reason
:class:`~palaia_hub.telegram.poller.LongPoller` is per bot: ``getUpdates``
is per token, and a bot whose token was revoked must back off on its own
without holding up a healthy one.

**Stopped before the secret store closes.** Every poll reads its bot's token
from the secret store for the duration of that one call
(:meth:`~palaia_hub.telegram.service.TelegramService.fetch_updates`), so the
lifespan cancels these tasks *before* it closes the store — the other order
would turn an ordinary shutdown into a burst of "cannot read secret" errors
from polls that were never going to be answered anyway.

**Configuration is read once.** Bots, routes and grants come from
``config.yaml`` at startup; a vault created later through the wizard is not
in the map an ``inbox`` route delivers into until the hub restarts. The
startup check below says so for every route it can already tell will fail,
instead of letting the first message find out.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from types import MappingProxyType

from .api import BotApi
from .poller import LongPoller
from .service import TelegramService

logger = logging.getLogger("palaia_hub.telegram.runtime")

#: The prefix of each poll task's name — ``telegram-poll:<bot key>`` — so a
#: task dump or a debugger names the bot a stuck task belongs to.
POLL_TASK_PREFIX = "telegram-poll:"


class TelegramRuntime:
    """The running Telegram connector: its service, its pollers, its client.

    Args:
        service: the connector, already built over the hub's secret store,
            messenger and vaults. Exposed as :attr:`service` — the app wires
            its event hook and mounts the webhook router over it.
        api: the Bot API client ``service`` was built with. Closed by
            :meth:`aclose` only when ``owns_api`` is set *and* it has an
            ``aclose`` — a client a test handed in is the test's to close.
        owns_api: whether this runtime created ``api`` (production does:
            :class:`~palaia_hub.telegram.api.HttpBotApi` holds a connection
            pool that must be released at shutdown).
        mode: the hub's operating mode, for the startup check — a webhook
            bot on a ``locked`` hub can never receive anything.
    """

    def __init__(
        self,
        service: TelegramService,
        api: BotApi,
        *,
        owns_api: bool = False,
        mode: str = "locked",
    ) -> None:
        self.service = service
        self._api = api
        self._owns_api = owns_api
        self._mode = mode
        # Built up front rather than in `start()`: a poller's offset and
        # failure count are the connector's live state, and a reader (the
        # dashboard panel, #439's second half) must find the same object
        # before, during and after the task that drives it.
        self._pollers: dict[str, LongPoller] = {
            bot.key: LongPoller(service, bot.key) for bot in service.polling_bots()
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._warned = False
        self._api_closed = False

    @property
    def pollers(self) -> Mapping[str, LongPoller]:
        """Bot key → its :class:`~palaia_hub.telegram.poller.LongPoller`,
        read-only. One entry per enabled ``transport: polling`` bot; a
        webhook bot or a switched-off one has none."""
        return MappingProxyType(self._pollers)

    @property
    def tasks(self) -> Mapping[str, asyncio.Task[None]]:
        """Bot key → the task running its poll loop, read-only. Empty before
        :meth:`start` and after :meth:`aclose`."""
        return MappingProxyType(self._tasks)

    def startup_warnings(self) -> list[str]:
        """Every configuration problem visible before the first message.

        Each one is a route or a bot that the config schema accepted — it is
        structurally fine — but that this particular running hub cannot
        serve. Returned rather than raised: a hub must start with a
        half-usable Telegram section (the other bots and routes still
        work), and the operator hears about the rest in the log. Names bot
        keys, chats and vault keys only — never a secret, nor a secret's
        name.
        """
        warnings: list[str] = []
        if self._mode == "locked":
            for bot in self.service.enabled_bots():
                if bot.transport == "webhook":
                    warnings.append(
                        f"telegram bot {bot.key!r} uses transport: webhook, but this "
                        "hub is in locked mode: a webhook needs a public URL, and a "
                        "locked hub has none, so Telegram cannot deliver to it. Fix: "
                        "set transport: polling for this bot, or switch the hub to "
                        "cloud or open mode."
                    )
        vaults = self.service.vault_keys
        for route in self.service.routes.routes:
            destination = route.destination
            if destination.kind == "inbox" and (destination.vault or "") not in vaults:
                warnings.append(
                    f"telegram route {route.bot}/{route.chat} delivers into the inbox "
                    f"of vault {destination.vault!r}, which this hub did not have when "
                    f"it started (vaults: {sorted(vaults) or 'none'}), so every "
                    "message it claims is refused for now. The route applies after a "
                    "restart once that vault exists."
                )
            if destination.kind == "messenger" and not self.service.has_messenger:
                warnings.append(
                    f"telegram route {route.bot}/{route.chat} delivers to the "
                    "messenger, but this hub was started without one, so every "
                    "message it claims is refused. Fix: route it to kind: inbox or "
                    "kind: event instead."
                )
        return warnings

    async def start(self) -> None:
        """Start one poll task per polling bot (idempotent).

        Returns immediately — the first ``getUpdates`` runs in the
        background, so a hub whose Telegram is unreachable still starts
        instantly. The startup check is logged on the first call only.
        """
        if not self._warned:
            self._warned = True
            for warning in self.startup_warnings():
                logger.warning("%s", warning)
        if self._api_closed:
            # Only reachable by starting a runtime whose own client was
            # already released — a second lifespan over one app. Polling
            # against a closed client would only fill the log.
            logger.warning(
                "telegram runtime was already shut down; not restarting its poll tasks"
            )
            return
        if self._tasks:
            return
        for key, poller in self._pollers.items():
            self._tasks[key] = asyncio.create_task(
                poller.run_forever(), name=f"{POLL_TASK_PREFIX}{key}"
            )
        if self._tasks:
            logger.info("telegram: long polling started for bot(s) %s", sorted(self._tasks))

    async def aclose(self) -> None:
        """Cancel every poll task, wait for it, then release the client.

        Idempotent, and never raises on a task that already died: the
        results are collected with ``return_exceptions=True`` rather than
        awaited one by one, because awaiting a task that failed re-raises
        its failure — and shutdown is the wrong moment to learn about it by
        crashing. Cancelling a task parked in a long poll is immediate: the
        ``getUpdates`` it is waiting on is simply abandoned.
        """
        tasks = dict(self._tasks)
        self._tasks.clear()
        for task in tasks.values():
            task.cancel()
        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks, results, strict=True):
                if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError
                ):
                    logger.warning(
                        "telegram poll task for bot %r had already stopped: %s: %s",
                        key,
                        type(result).__name__,
                        result,
                    )
        if self._owns_api and not self._api_closed:
            self._api_closed = True
            closer = getattr(self._api, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception as exc:  # noqa: BLE001 — shutdown must finish
                    logger.warning(
                        "closing the Telegram API client failed: %s", type(exc).__name__
                    )


__all__ = ["POLL_TASK_PREFIX", "TelegramRuntime"]
