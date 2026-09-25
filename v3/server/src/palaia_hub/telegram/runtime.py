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

**Configuration applies live** (issue #463). Bots, routes and grants come
from ``config.yaml`` at startup, and the dashboard's editor hands every
saved change to :meth:`TelegramRuntime.apply_settings`, which swaps the
service's settings and starts or stops poll tasks to match — no restart.
A bot that keeps polling keeps its poller, and with it the offset that is
Telegram's only acknowledgement. What is still fixed at startup is the
vault map an ``inbox`` route delivers into: a vault created later through
the wizard is reachable after a restart. The configuration check below says
so for every route it can already tell will fail — at startup in the log,
and after every edit in the editor's answer.

**The dashboard's one outbound call lives here too** (issue #439):
:meth:`TelegramRuntime.check_bot` runs ``getMe`` when the operator asks and
caches the answer, so the panel's status read — refetched on every
``telegram.*`` event — never calls Telegram itself.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .api import BotApi, summary_line
from .models import BotCheck, TelegramError, TelegramSettings
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
        now: the hub clock, unix seconds, shared with the pollers — stamps
            what the dashboard panel reads.
    """

    def __init__(
        self,
        service: TelegramService,
        api: BotApi,
        *,
        owns_api: bool = False,
        mode: str = "locked",
        now: Any = time.time,
    ) -> None:
        self.service = service
        self._api = api
        self._owns_api = owns_api
        self._mode = mode
        self._now = now
        # Built up front rather than in `start()`: a poller's offset and
        # failure count are the connector's live state, and a reader (the
        # dashboard panel, #439's second half) must find the same object
        # before, during and after the task that drives it.
        self._pollers: dict[str, LongPoller] = {
            bot.key: LongPoller(service, bot.key, now=now) for bot in service.polling_bots()
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._last_checks: dict[str, BotCheck] = {}
        self._warned = False
        self._api_closed = False
        #: Set by :meth:`start`, cleared by :meth:`aclose` — whether a bot
        #: added by :meth:`apply_settings` should get its poll task now. Not
        #: derivable from :attr:`tasks`: a hub with no polling bot yet has
        #: none, and is started all the same.
        self._started = False
        #: Serialises :meth:`apply_settings` against itself, so two saves
        #: in quick succession cannot interleave their poller changes.
        self._apply_lock = asyncio.Lock()

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

    @property
    def last_checks(self) -> Mapping[str, BotCheck]:
        """Bot key → the result of its last :meth:`check_bot`, read-only.
        In memory: a restart forgets them, and the panel says "not checked
        yet" again until the next click."""
        return MappingProxyType(self._last_checks)

    async def check_bot(self, key: str) -> BotCheck:
        """Ask Telegram whether this bot's token works (``getMe``) and cache
        the answer for the dashboard.

        Only ever on the operator's click. A failure is a *result*
        (``ok=False`` with the scrubbed reason), not an error: "Telegram
        refused this token" — or "no token is stored yet" — is exactly what
        the check exists to say.

        Raises:
            UnknownBotError: no such bot, or it is switched off — asked
                before anything else, so it is never mistaken for a failed
                check.
        """
        self.service.require_bot(key)
        try:
            me = await self.service.check_bot(key)
        except TelegramError as exc:
            result = BotCheck(
                ok=False, checked_at=float(self._now()), error=summary_line(str(exc))
            )
        else:
            username = me.get("username")
            result = BotCheck(
                ok=True,
                username=username if isinstance(username, str) else None,
                checked_at=float(self._now()),
            )
        self._last_checks[key] = result
        return result

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
        if self._started:
            return
        self._started = True
        for key in self._pollers:
            self._start_task(key)
        if self._tasks:
            logger.info("telegram: long polling started for bot(s) %s", sorted(self._tasks))

    def _start_task(self, key: str) -> None:
        self._tasks[key] = asyncio.create_task(
            self._pollers[key].run_forever(), name=f"{POLL_TASK_PREFIX}{key}"
        )

    async def _stop_tasks(self, keys: list[str]) -> None:
        """Cancel these bots' poll tasks and wait for them — never raising
        on one that had already died (see :meth:`aclose`)."""
        tasks = {key: self._tasks.pop(key) for key in keys if key in self._tasks}
        for task in tasks.values():
            task.cancel()
        if not tasks:
            return
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

    async def apply_settings(self, settings: TelegramSettings) -> list[str]:
        """Run the connector on an edited ``telegram:`` section, live.

        ``settings`` is already validated — cross-references included
        (:meth:`~palaia_hub.telegram.models.TelegramSettings.
        check_consistency`); this method only makes the running connector
        match it:

        * the service swaps its settings and routing table
          (:meth:`~palaia_hub.telegram.service.TelegramService.
          apply_settings`), so the next message, send or tool call follows
          the new rules;
        * a bot that stops polling — removed, switched off, moved to a
          webhook — has its task cancelled and its poller dropped;
        * a bot that starts polling gets a poller, and a task if the
          runtime is running;
        * a bot that keeps polling **under the same token secret** keeps its
          poller and its task untouched. The offset is the only thing that
          acknowledges an update to Telegram: dropping it would re-deliver
          the last batch, and carrying it over to a *different* bot's token
          would skip that bot's updates — so a changed ``token_secret``
          gets a fresh poller.

        A removed bot's cached connection check is forgotten, and so is one
        whose token secret changed: it described another token.

        Returns:
            The configuration check (:meth:`startup_warnings`) against the
            new settings — what the editor shows the operator, and what is
            logged.
        """
        async with self._apply_lock:
            previous = {bot.key: bot for bot in self.service.settings.bots}
            self.service.apply_settings(settings)
            wanted = {bot.key: bot for bot in self.service.polling_bots()}
            stale = [
                key
                for key in self._pollers
                if key not in wanted or wanted[key].token_secret != previous[key].token_secret
            ]
            await self._stop_tasks(stale)
            for key in stale:
                del self._pollers[key]
            for key in wanted:
                if key in self._pollers:
                    continue
                self._pollers[key] = LongPoller(self.service, key, now=self._now)
                if self._started and not self._api_closed:
                    self._start_task(key)
            current = {bot.key: bot for bot in settings.bots}
            for key in list(self._last_checks):
                bot = current.get(key)
                old = previous.get(key)
                if bot is None or old is None or bot.token_secret != old.token_secret:
                    del self._last_checks[key]
            warnings = self.startup_warnings()
        for warning in warnings:
            logger.warning("%s", warning)
        return warnings

    async def secret_changed(self, name: str) -> None:
        """React to a stored secret being replaced or removed.

        Wired as a ``/api/secrets`` change hook: when the dashboard stores a
        bot's token, a poller of that bot sitting in its backoff (it failed
        because there was no token) is restarted at once instead of after
        up to :data:`~palaia_hub.telegram.poller.MAX_BACKOFF_SECONDS`, and
        its cached connection check — which described the old token, or
        none — is forgotten. The poller object, and its offset, are kept.
        """
        async with self._apply_lock:
            affected = [
                bot.key
                for bot in self.service.settings.bots
                if name in (bot.token_secret, bot.webhook_secret)
            ]
            for key in affected:
                self._last_checks.pop(key, None)
            restart = [
                key
                for key in affected
                if key in self._tasks and self._pollers[key].consecutive_failures > 0
            ]
            await self._stop_tasks(restart)
            if self._started and not self._api_closed:
                for key in restart:
                    self._start_task(key)

    async def aclose(self) -> None:
        """Cancel every poll task, wait for it, then release the client.

        Idempotent, and never raises on a task that already died: the
        results are collected with ``return_exceptions=True`` rather than
        awaited one by one, because awaiting a task that failed re-raises
        its failure — and shutdown is the wrong moment to learn about it by
        crashing. Cancelling a task parked in a long poll is immediate: the
        ``getUpdates`` it is waiting on is simply abandoned.
        """
        self._started = False
        await self._stop_tasks(list(self._tasks))
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
