"""Long polling (issue #411): the transport that works behind NAT.

The default, and the only one a ``locked`` hub can use: ``getUpdates`` is an
outbound HTTPS request that Telegram holds open until something happens, so
the hub needs no public URL, no certificate and no inbound port. A webhook
needs all three, which is why it is the opt-in
(:mod:`palaia_hub.telegram.webhook`) and this is not.

**The offset is the whole protocol.** Telegram redelivers every update until
it is acknowledged, and the acknowledgement is implicit: the next
``getUpdates`` with ``offset = max(update_id) + 1`` confirms everything
below it. Two consequences the code below takes seriously:

1. **The offset advances past updates nothing understood.** A callback query,
   or a message shape from an API version newer than this connector, must
   still move the offset — otherwise the poller re-fetches the same unusable
   update forever and never sees the next real one. This is why
   :func:`~palaia_hub.telegram.updates.normalise_update` returns ``None``
   rather than raising, and why the offset is computed from the raw
   ``update_id`` before anything is dispatched.
2. **The offset advances past updates that failed to deliver.** A vault that
   refuses a capture is a hub-side problem to fix, not a reason to replay the
   same message on a loop; the failure is reported in the outcome and on the
   event bus instead.

**The loop never dies of a transport error.** A network blip, a 502 from
Telegram, a token that was just rotated — each is logged and retried after a
backoff that grows to :data:`MAX_BACKOFF_SECONDS`, because the alternative
(a task that exits) is a connector that is silently off until someone
restarts the hub.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .models import DispatchOutcome, TelegramError
from .service import TelegramService

logger = logging.getLogger("palaia_hub.telegram.poller")

#: First retry delay after a failed poll, doubling up to the cap below.
BASE_BACKOFF_SECONDS = 1.0

#: The longest the poller waits between retries. A minute: long enough not to
#: hammer an API that is having a bad day, short enough that a hub recovers on
#: its own while the operator is still reading the alert.
MAX_BACKOFF_SECONDS = 60.0


class LongPoller:
    """One poll loop for one bot.

    One per bot rather than one shared loop, because ``getUpdates`` is
    per-token by construction: there is no batched form, and a slow or broken
    bot must not hold up a healthy one.
    """

    def __init__(
        self,
        service: TelegramService,
        bot: str,
        *,
        timeout: float | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._service = service
        self.bot = bot
        self._timeout = (
            timeout if timeout is not None else service.settings.poll_timeout_seconds
        )
        self._sleep = sleep
        #: ``None`` until the first batch: the first ``getUpdates`` of a
        #: process deliberately sends no offset, so Telegram replies with
        #: whatever it is still holding rather than with nothing.
        self.offset: int | None = None
        self.consecutive_failures = 0

    async def poll_once(self) -> list[DispatchOutcome]:
        """Fetch one batch, advance the offset, dispatch every update.

        Returns one outcome per update — including the ones that normalised
        to nothing, so a caller counting outcomes is counting updates.

        Raises:
            TelegramError: only from the *fetch*. A dispatch never raises
                (see :meth:`~palaia_hub.telegram.service.TelegramService.
                handle_update`), so an exception out of this method always
                means "could not talk to Telegram", which is what
                :meth:`run_forever` backs off on.
        """
        updates = await self._service.fetch_updates(
            self.bot, offset=self.offset, timeout=self._timeout
        )
        # Advance first, dispatch second — see the module docstring.
        highest = max(
            (u["update_id"] for u in updates if isinstance(u.get("update_id"), int)),
            default=None,
        )
        if highest is not None:
            self.offset = highest + 1
        outcomes = [await self._service.handle_update(self.bot, update) for update in updates]
        return outcomes

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        """Poll until ``stop`` is set (or the task is cancelled).

        Cancellation is the hub's shutdown path and is re-raised untouched;
        every other failure is a transport problem and is backed off.
        """
        while stop is None or not stop.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except TelegramError as exc:
                await self._backoff(str(exc))
            except Exception as exc:  # pragma: no cover - defensive
                await self._backoff(f"unexpected {type(exc).__name__}: {exc}")
            else:
                self.consecutive_failures = 0

    async def _backoff(self, reason: str) -> None:
        self.consecutive_failures += 1
        delay = min(
            BASE_BACKOFF_SECONDS * (2 ** (self.consecutive_failures - 1)), MAX_BACKOFF_SECONDS
        )
        logger.warning(
            "telegram poll for bot %r failed (%d in a row), retrying in %.0fs: %s",
            self.bot,
            self.consecutive_failures,
            delay,
            reason,
        )
        await self._sleep(delay)


__all__ = ["BASE_BACKOFF_SECONDS", "MAX_BACKOFF_SECONDS", "LongPoller"]
