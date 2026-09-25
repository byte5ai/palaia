"""The connector's process lifecycle (issue #439):
:class:`~palaia_hub.telegram.runtime.TelegramRuntime`.

Unit-level: a real :class:`~palaia_hub.telegram.service.TelegramService`
over the fakes in ``conftest.py``, no app, no lifespan. What the production
assembly does with it — the poll tasks running inside the hub's lifespan,
the webhook route mounted, the tools on a live profile — is
``test_serve_wiring.py``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from palaia_hub.telegram.api import TelegramApiError
from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.runtime import POLL_TASK_PREFIX, TelegramRuntime
from palaia_hub.telegram.service import TelegramService

from .conftest import (
    BOT_A_TOKEN,
    BOT_B_TOKEN,
    TWO_BOT_SETTINGS,
    FakeBotApi,
    FakeMessenger,
    FakeSecrets,
    FakeVault,
    message_update,
)

pytestmark = pytest.mark.anyio

HOOK_SECRET = "hook-secret-value-not-a-token"  # noqa: S105 - test fixture

#: One of each: a polling bot, a webhook bot, and a switched-off bot.
MIXED_SETTINGS: dict[str, Any] = {
    "bots": [
        {"key": "support", "token_secret": "telegram_support"},
        {
            "key": "hooked",
            "token_secret": "telegram_hooked",
            "transport": "webhook",
            "webhook_secret": "telegram_hooked_hook",
        },
        {"key": "asleep", "token_secret": "telegram_asleep", "enabled": False},
    ],
    "routes": [
        {"bot": "support", "chat": "-1001", "destination": {"kind": "messenger", "to": "ops"}},
        {"bot": "support", "chat": "-1002", "destination": {"kind": "inbox", "vault": "work"}},
        {"bot": "hooked", "chat": "*", "destination": {"kind": "inbox", "vault": "later"}},
    ],
}


@pytest.fixture
def records() -> Iterator[list[logging.LogRecord]]:
    """Every record under ``palaia_hub.telegram``, captured directly.

    A handler on the connector's own logger rather than ``caplog``'s root
    handler: :func:`palaia_hub.logging.setup_logging` (which any earlier
    test that built an app has run) sets ``propagate = False`` on the
    ``palaia_hub`` tree, so a root-level capture would see nothing.
    """
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _Capture(level=logging.DEBUG)
    logger = logging.getLogger("palaia_hub.telegram")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield captured
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _mixed(api: FakeBotApi, **service_kwargs: Any) -> TelegramService:
    return TelegramService(
        TelegramSettings.model_validate(MIXED_SETTINGS),
        api,
        FakeSecrets(
            {
                "telegram_support": BOT_A_TOKEN,
                "telegram_hooked": BOT_B_TOKEN,
                "telegram_hooked_hook": HOOK_SECRET,
            }
        ),
        **service_kwargs,
    )


async def _until(predicate: Any, *, rounds: int = 500) -> None:
    """Yield to the loop until ``predicate()`` holds (or fail loudly)."""
    for _ in range(rounds):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never became true")


# ---------------------------------------------------------------- pollers


def test_only_an_enabled_polling_bot_gets_a_poller() -> None:
    runtime = TelegramRuntime(_mixed(FakeBotApi()), FakeBotApi())
    assert set(runtime.pollers) == {"support"}
    # Read-only: the pollers are the connector's state, not a knob.
    with pytest.raises(TypeError):
        runtime.pollers["hooked"] = runtime.pollers["support"]  # type: ignore[index]


async def test_start_runs_one_named_task_per_polling_bot(
    service: TelegramService, api: FakeBotApi
) -> None:
    api.park_when_empty = True  # `api` is the fake `service` was built over
    runtime = TelegramRuntime(service, api)

    await runtime.start()
    try:
        assert set(runtime.tasks) == {"support", "personal"}
        names = {task.get_name() for task in runtime.tasks.values()}
        assert names == {f"{POLL_TASK_PREFIX}support", f"{POLL_TASK_PREFIX}personal"}
        await _until(lambda: len(api.get_updates_calls) >= 2)
        assert {call["token"] for call in api.get_updates_calls} == {BOT_A_TOKEN, BOT_B_TOKEN}
    finally:
        await runtime.aclose()


async def test_a_polled_update_is_routed_like_any_other(
    service: TelegramService, api: FakeBotApi, messenger: FakeMessenger
) -> None:
    api.queue = [[message_update(5, chat_id=-1001, text="from the poll task")]]
    api.park_when_empty = True
    runtime = TelegramRuntime(service, api)

    await runtime.start()
    try:
        await _until(lambda: bool(messenger.sends))
    finally:
        await runtime.aclose()
    assert messenger.sends[0]["to"] == "ops-agent"
    assert "from the poll task" in messenger.sends[0]["body"]
    # The acknowledgement for the next poll: past the update just handled.
    assert runtime.pollers["support"].offset == 6


# ------------------------------------------------------ start / aclose


async def test_start_and_aclose_are_idempotent(service: TelegramService, api: FakeBotApi) -> None:
    api.park_when_empty = True
    runtime = TelegramRuntime(service, api)

    await runtime.start()
    first = dict(runtime.tasks)
    await runtime.start()
    assert dict(runtime.tasks) == first  # the same tasks, not a second set

    await runtime.aclose()
    await runtime.aclose()
    assert runtime.tasks == {}
    assert all(task.done() for task in first.values())


async def test_aclose_cancels_a_poller_parked_in_a_long_poll(
    service: TelegramService, api: FakeBotApi
) -> None:
    api.park_when_empty = True
    runtime = TelegramRuntime(service, api)
    await runtime.start()
    tasks = list(runtime.tasks.values())
    await _until(lambda: api.parked_polls >= 2)

    await asyncio.wait_for(runtime.aclose(), timeout=5)

    assert all(task.done() for task in tasks)
    assert all(task.cancelled() for task in tasks)
    assert api.cancelled_polls == 2


async def test_aclose_does_not_raise_for_a_task_that_already_died(
    service: TelegramService, api: FakeBotApi, records: list[logging.LogRecord]
) -> None:
    runtime = TelegramRuntime(service, api)

    async def _dies() -> None:
        raise RuntimeError("poll loop fell over")

    # The loop itself never dies of an ordinary failure (LongPoller backs
    # off instead); this is the "something truly unexpected" case.
    for poller in runtime.pollers.values():
        poller.run_forever = _dies  # type: ignore[method-assign]
    await runtime.start()
    tasks = list(runtime.tasks.values())
    await _until(lambda: all(task.done() for task in tasks))

    await runtime.aclose()  # must not raise

    assert any("had already stopped" in r.getMessage() for r in records)


async def test_an_owned_client_is_closed_and_a_borrowed_one_is_not(
    service: TelegramService,
) -> None:
    borrowed = FakeBotApi(park_when_empty=True)
    await TelegramRuntime(service, borrowed).aclose()
    assert borrowed.closed is False

    owned = FakeBotApi(park_when_empty=True)
    runtime = TelegramRuntime(service, owned, owns_api=True)
    await runtime.start()
    await runtime.aclose()
    await runtime.aclose()
    assert owned.closed is True


async def test_a_client_without_aclose_is_fine_even_when_owned(service: TelegramService) -> None:
    class _NoClose:
        pass

    runtime = TelegramRuntime(service, _NoClose(), owns_api=True)  # type: ignore[arg-type]
    await runtime.aclose()


async def test_a_closed_runtime_with_an_owned_client_does_not_restart(
    service: TelegramService, api: FakeBotApi
) -> None:
    api.park_when_empty = True
    runtime = TelegramRuntime(service, api, owns_api=True)
    await runtime.start()
    await runtime.aclose()

    await runtime.start()
    try:
        assert runtime.tasks == {}
    finally:
        await runtime.aclose()


# ------------------------------------------------------- startup warnings


def test_a_fully_wired_cloud_hub_has_nothing_to_warn_about() -> None:
    service = _mixed(
        FakeBotApi(), messenger=FakeMessenger(), vaults={"work": FakeVault(), "later": FakeVault()}
    )
    assert TelegramRuntime(service, FakeBotApi(), mode="cloud").startup_warnings() == []


def test_a_webhook_bot_on_a_locked_hub_is_named() -> None:
    service = _mixed(
        FakeBotApi(), messenger=FakeMessenger(), vaults={"work": FakeVault(), "later": FakeVault()}
    )
    warnings = TelegramRuntime(service, FakeBotApi(), mode="locked").startup_warnings()
    assert len(warnings) == 1
    assert "'hooked'" in warnings[0]
    assert "public URL" in warnings[0]
    assert "polling" in warnings[0]


def test_an_inbox_route_to_a_vault_the_hub_lacks_is_named() -> None:
    service = _mixed(FakeBotApi(), messenger=FakeMessenger(), vaults={"work": FakeVault()})
    warnings = TelegramRuntime(service, FakeBotApi(), mode="cloud").startup_warnings()
    assert len(warnings) == 1
    assert "'later'" in warnings[0]
    assert "after a restart" in warnings[0]


def test_a_messenger_route_with_no_messenger_is_named() -> None:
    service = _mixed(FakeBotApi(), vaults={"work": FakeVault(), "later": FakeVault()})
    warnings = TelegramRuntime(service, FakeBotApi(), mode="cloud").startup_warnings()
    assert len(warnings) == 1
    assert "hooked" not in warnings[0]
    assert "support/-1001" in warnings[0]
    assert "messenger" in warnings[0]


async def test_start_logs_every_warning_once_and_never_a_secret(
    records: list[logging.LogRecord],
) -> None:
    api = FakeBotApi(park_when_empty=True)
    # A failing poll too, so the poller's own warning is in the capture.
    api.fail_with = TelegramApiError("getUpdates", f"bad gateway for bot{BOT_A_TOKEN}")
    runtime = TelegramRuntime(_mixed(api), api, mode="locked")

    await runtime.start()
    try:
        await _until(
            lambda: any("telegram poll for bot" in r.getMessage() for r in records)
        )
        await runtime.start()  # a second start does not repeat the check
    finally:
        await runtime.aclose()

    startup = [r for r in records if r.name == "palaia_hub.telegram.runtime"]
    warned = [r.getMessage() for r in startup if r.levelno == logging.WARNING]
    # Webhook-on-locked, the two inbox routes to vaults this hub lacks, and
    # the messenger route with no messenger.
    assert len(warned) == 4, warned
    joined = "\n".join(r.getMessage() for r in records)
    for secret in (BOT_A_TOKEN, BOT_B_TOKEN, HOOK_SECRET):
        assert secret not in joined


async def test_a_second_bot_without_a_token_does_not_stop_the_first(
    records: list[logging.LogRecord],
) -> None:
    """One bot whose token is not stored yet — the day-one mistake — backs
    off on its own task; the other bot keeps polling."""
    api = FakeBotApi(park_when_empty=True)
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS),
        api,
        FakeSecrets({"telegram_support": BOT_A_TOKEN}),  # nothing for "personal"
    )
    runtime = TelegramRuntime(service, api)
    await runtime.start()
    try:
        await _until(lambda: bool(api.get_updates_calls))
        await _until(lambda: runtime.pollers["personal"].consecutive_failures >= 1)
        assert not runtime.tasks["support"].done()
        assert not runtime.tasks["personal"].done()
    finally:
        await runtime.aclose()
    assert {call["token"] for call in api.get_updates_calls} == {BOT_A_TOKEN}
