"""Long polling (issue #411) — half of the fourth acceptance criterion
("long polling and webhook mode both covered by tests against a mocked Bot
API"); the other half is ``test_webhook.py``.

Almost every test here is about the *offset*, because the offset is the
acknowledgement: get it wrong in one direction and the connector replays the
same update forever, wrong in the other and it loses messages it never
delivered.
"""

from __future__ import annotations

import pytest

from palaia_hub.telegram.api import TelegramApiError
from palaia_hub.telegram.models import ALLOWED_UPDATES
from palaia_hub.telegram.poller import MAX_BACKOFF_SECONDS, LongPoller
from palaia_hub.telegram.service import TelegramService

from .conftest import BOT_A_TOKEN, FakeBotApi, message_update


@pytest.mark.anyio
async def test_the_first_poll_sends_no_offset(
    service: TelegramService, api: FakeBotApi
) -> None:
    """Telegram then hands over whatever it is still holding, rather than
    nothing — which is what an operator restarting the hub expects."""
    poller = LongPoller(service, "support")
    await poller.poll_once()
    assert api.get_updates_calls[0]["offset"] is None


@pytest.mark.anyio
async def test_the_poll_asks_only_for_the_update_types_this_connector_handles(
    service: TelegramService, api: FakeBotApi
) -> None:
    await LongPoller(service, "support").poll_once()
    assert api.get_updates_calls[0]["allowed_updates"] == ALLOWED_UPDATES


@pytest.mark.anyio
async def test_the_poll_uses_the_bots_own_token(
    service: TelegramService, api: FakeBotApi
) -> None:
    await LongPoller(service, "support").poll_once()
    assert api.get_updates_calls[0]["token"] == BOT_A_TOKEN


@pytest.mark.anyio
async def test_the_offset_moves_past_the_highest_update_seen(
    service: TelegramService, api: FakeBotApi
) -> None:
    api.queue = [
        [message_update(10, chat_id=-1001), message_update(12, chat_id=-1001)],
        [],
    ]
    poller = LongPoller(service, "support")
    await poller.poll_once()
    assert poller.offset == 13
    await poller.poll_once()
    assert api.get_updates_calls[1]["offset"] == 13


@pytest.mark.anyio
async def test_the_offset_moves_past_an_update_nothing_understood(
    service: TelegramService, api: FakeBotApi
) -> None:
    """The failure this guards against is the nastiest one available: an
    update type this connector has never heard of re-fetched forever, with
    every real message behind it never seen."""
    api.queue = [[{"update_id": 21, "callback_query": {"id": "x"}}]]
    poller = LongPoller(service, "support")
    outcomes = await poller.poll_once()
    assert poller.offset == 22
    assert len(outcomes) == 1 and outcomes[0].routed is False


@pytest.mark.anyio
async def test_the_offset_moves_past_a_message_that_failed_to_deliver(
    service: TelegramService, api: FakeBotApi, vault  # noqa: ANN001
) -> None:
    """A vault that refuses a capture is a hub-side problem to fix, not a
    reason to replay the same message on a loop."""

    async def boom(**kwargs: object) -> None:
        raise RuntimeError("vault is read-only")

    vault.capture = boom  # type: ignore[method-assign]
    api.queue = [[message_update(30, chat_id=-1002)]]
    poller = LongPoller(service, "personal")
    outcomes = await poller.poll_once()
    assert poller.offset == 31
    assert outcomes[0].routed is True and outcomes[0].delivered is False
    assert "vault is read-only" in outcomes[0].detail


@pytest.mark.anyio
async def test_an_empty_batch_leaves_the_offset_alone(
    service: TelegramService, api: FakeBotApi
) -> None:
    api.queue = [[message_update(40, chat_id=-1001)], []]
    poller = LongPoller(service, "support")
    await poller.poll_once()
    await poller.poll_once()
    assert poller.offset == 41


@pytest.mark.anyio
async def test_every_update_in_a_batch_is_dispatched(
    service: TelegramService, api: FakeBotApi, messenger  # noqa: ANN001
) -> None:
    api.queue = [
        [
            message_update(50, chat_id=-1001, message_id=1, text="one"),
            message_update(51, chat_id=-1001, message_id=2, text="two"),
        ]
    ]
    outcomes = await LongPoller(service, "support").poll_once()
    assert len(outcomes) == 2
    assert [s["body"].splitlines()[-1] for s in messenger.sends] == ["one", "two"]


@pytest.mark.anyio
async def test_a_transport_failure_backs_off_instead_of_ending_the_loop(
    service: TelegramService, api: FakeBotApi
) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    poller = LongPoller(service, "support", sleep=sleep)
    api.fail_with = TelegramApiError("getUpdates", "gateway timeout", status=504)
    for _ in range(4):
        try:
            await poller.poll_once()
        except TelegramApiError:
            await poller._backoff("test")  # noqa: SLF001 - the unit under test
    assert slept == [1.0, 2.0, 4.0, 8.0]
    assert max(slept) <= MAX_BACKOFF_SECONDS


@pytest.mark.anyio
async def test_run_forever_stops_when_asked(service: TelegramService, api: FakeBotApi) -> None:
    import asyncio

    stop = asyncio.Event()
    api.queue = [[message_update(60, chat_id=-1001)]]
    poller = LongPoller(service, "support")

    async def run() -> None:
        await poller.run_forever(stop)

    task = asyncio.create_task(run())
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1)
    assert poller.offset == 61


# -- what the dashboard panel reads (issue #439) ------------------------------


async def _no_sleep(seconds: float) -> None:
    return None


async def _cycle(poller: LongPoller) -> None:
    """One turn of :meth:`LongPoller.run_forever`, without the loop."""
    try:
        await poller.poll_once()
    except TelegramApiError as exc:
        await poller._backoff(str(exc))  # noqa: SLF001 - the unit under test


@pytest.mark.anyio
async def test_a_poll_telegram_answered_is_stamped_with_the_hub_clock(
    service: TelegramService,
) -> None:
    poller = LongPoller(service, "support", now=lambda: 1234.5)
    await poller.poll_once()
    assert poller.last_ok_at == 1234.5
    assert poller.last_error is None and poller.last_error_at is None


@pytest.mark.anyio
async def test_a_failure_is_kept_as_one_scrubbed_line_through_a_recovery(
    service: TelegramService, api: FakeBotApi
) -> None:
    clock = iter([10.0, 20.0])
    poller = LongPoller(service, "support", sleep=_no_sleep, now=lambda: next(clock))
    await poller._backoff(  # noqa: SLF001 - the unit under test
        f"unexpected ConnectError: /bot{BOT_A_TOKEN}/getUpdates\n" + "x" * 500
    )
    assert poller.last_error is not None
    assert BOT_A_TOKEN not in poller.last_error
    assert "\n" not in poller.last_error and len(poller.last_error) <= 200
    assert poller.last_error_at == 10.0

    await poller.poll_once()
    assert poller.consecutive_failures == 0
    assert poller.last_ok_at == 20.0
    # Kept on purpose: "failed at 10, fine since 20" is worth reading.
    assert poller.last_error is not None


@pytest.mark.anyio
async def test_the_bot_state_event_fires_on_a_transition_only(
    service: TelegramService, api: FakeBotApi, bus  # noqa: ANN001
) -> None:
    poller = LongPoller(service, "support", sleep=_no_sleep)
    await _cycle(poller)  # the first answer is not news: no event
    assert bus.named("telegram.bot.state") == []

    api.fail_with = TelegramApiError("getUpdates", f"Unauthorized {BOT_A_TOKEN}", status=401)
    for _ in range(3):
        await _cycle(poller)
    api.fail_with = None
    for _ in range(2):
        await _cycle(poller)

    states = bus.named("telegram.bot.state")
    assert [(e["bot"], e["state"]) for e in states] == [("support", "failing"), ("support", "ok")]
    assert "401" in states[0]["detail"]
    assert states[1]["detail"] == ""
    assert BOT_A_TOKEN not in repr(states)
