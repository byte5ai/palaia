"""The dashboard's Telegram panel, server side (issue #439): what
``/api/telegram`` reports, and what the connector records for it.

Unit-level: the router mounted on a bare app over a real
:class:`~palaia_hub.telegram.runtime.TelegramRuntime` and the fakes in
``conftest.py``. That the router is mounted behind the admin session in a
real :func:`palaia_hub.app.create_app` is the route walk's job
(``tests/test_admin_session.py``); that nothing in the status response can
carry a token is ``test_token_never_leaks.py``'s.

Three properties matter more than the shape:

* **The status read never calls Telegram** — the panel refetches it on
  every ``telegram.*`` event, so a read that reached the Bot API would be a
  request per message.
* **No message text, anywhere** — ADR-006's "no message store" holds: the
  recent list is metadata, bounded, and in memory.
* **Recording can never cost a delivery** — ``handle_update`` keeps its
  never-raises guarantee even when the bookkeeping fails.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ValidationError

from palaia_hub.telegram.api import TelegramApiError
from palaia_hub.telegram.dashboard_api import build_telegram_dashboard_router
from palaia_hub.telegram.models import DEFAULT_RECENT_SIZE, TelegramSettings
from palaia_hub.telegram.runtime import TelegramRuntime
from palaia_hub.telegram.service import TelegramService

from .conftest import (
    BOT_A_TOKEN,
    BOT_B_TOKEN,
    FakeBotApi,
    FakeMessenger,
    FakeSecrets,
    FakeVault,
    RecordingBus,
    message_update,
)

pytestmark = pytest.mark.anyio

NOW = 1_800_000_000.0

#: A polling bot with its token, a webhook bot whose echo secret was never
#: stored, and a switched-off bot with nothing stored at all.
PANEL_SETTINGS: dict[str, Any] = {
    "bots": [
        {"key": "support", "token_secret": "telegram_support", "label": "Support bot"},
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
        {"bot": "hooked", "chat": "*", "destination": {"kind": "event"}},
    ],
}


@pytest.fixture
def secrets() -> FakeSecrets:
    return FakeSecrets({"telegram_support": BOT_A_TOKEN, "telegram_hooked": BOT_B_TOKEN})


@pytest.fixture
def service(
    api: FakeBotApi,
    secrets: FakeSecrets,
    messenger: FakeMessenger,
    vault: FakeVault,
    bus: RecordingBus,
) -> TelegramService:
    return TelegramService(
        TelegramSettings.model_validate(PANEL_SETTINGS),
        api,
        secrets,
        messenger=messenger,
        vaults={"work": vault},
        publish=bus,
        now=lambda: NOW,
    )


@pytest.fixture
def runtime(service: TelegramService, api: FakeBotApi) -> TelegramRuntime:
    return TelegramRuntime(service, api, now=lambda: NOW)


@pytest.fixture
def app(runtime: TelegramRuntime, secrets: FakeSecrets) -> FastAPI:
    app = FastAPI()
    app.include_router(build_telegram_dashboard_router(runtime, secrets))
    return app


async def _request(app: FastAPI, method: str, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as client:
        return await client.request(method, path)


async def _status(app: FastAPI) -> dict[str, Any]:
    response = await _request(app, "GET", "/api/telegram/status")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _bot(status: dict[str, Any], key: str) -> dict[str, Any]:
    return next(bot for bot in status["bots"] if bot["key"] == key)


# ------------------------------------------------------------------ status


async def test_the_status_lists_every_bot_and_never_calls_telegram(
    app: FastAPI, api: FakeBotApi
) -> None:
    status = await _status(app)

    assert [bot["key"] for bot in status["bots"]] == ["support", "hooked", "asleep"]
    support = _bot(status, "support")
    assert support["label"] == "Support bot"
    assert support["token_stored"] is True
    assert support["webhook_secret_stored"] is None
    assert support["polling"] == {
        "running": False,
        "last_ok_at": None,
        "last_error": None,
        "last_error_at": None,
        "consecutive_failures": 0,
    }
    assert support["last_update_at"] is None and support["last_check"] is None

    hooked = _bot(status, "hooked")
    assert hooked["label"] == "hooked"  # no label configured: the key
    assert hooked["polling"] is None
    assert hooked["webhook_secret_stored"] is False

    asleep = _bot(status, "asleep")
    assert asleep["enabled"] is False
    assert asleep["token_stored"] is False
    assert asleep["polling"] is None

    # The read is answered from memory — the Bot API was never touched.
    assert api.get_me_calls == 0
    assert api.get_updates_calls == []


async def test_the_routes_are_the_routing_table_in_plain_form(app: FastAPI) -> None:
    status = await _status(app)
    assert status["routes"] == [
        {"bot": "support", "chat": "-1001", "kind": "messenger", "destination": "messenger:ops"},
        {"bot": "support", "chat": "-1002", "kind": "inbox", "destination": "inbox:work"},
        {"bot": "hooked", "chat": "*", "kind": "event", "destination": "event"},
    ]


async def test_a_running_poll_task_and_its_state_are_reported(
    app: FastAPI, runtime: TelegramRuntime, api: FakeBotApi
) -> None:
    api.park_when_empty = True
    await runtime.start()
    try:
        status = await _status(app)
    finally:
        await runtime.aclose()
    assert _bot(status, "support")["polling"]["running"] is True
    assert _bot(await _status(app), "support")["polling"]["running"] is False


# ---------------------------------------------------------- recent messages


async def test_recent_messages_are_newest_first_with_no_text_and_no_sender(
    app: FastAPI, service: TelegramService
) -> None:
    await service.handle_update(
        "support", message_update(1, chat_id=-1001, message_id=11, text="relayed words")
    )
    await service.handle_update(
        "hooked", message_update(2, chat_id=-1005, message_id=12, text="evented words")
    )
    await service.handle_update(
        "support",
        message_update(
            3, chat_id=-1003, message_id=13, text="dropped words", chat_username="OpsRoom"
        ),
    )

    response = await _request(app, "GET", "/api/telegram/status")
    for words in ("relayed words", "evented words", "dropped words", "Lovelace", "sender"):
        assert words not in response.text

    recent = response.json()["recent"]
    assert [entry["message_id"] for entry in recent] == [13, 12, 11]
    dropped, evented, relayed = recent
    assert dropped["routed"] is False and dropped["delivered"] is False
    # What an operator writing their first route needs, most specific first.
    assert dropped["candidates"] == ["-1003", "@opsroom", "*"]
    assert dropped["chat_username"] == "OpsRoom"
    assert evented["destination"] == "event" and evented["delivered"] is True
    assert relayed["destination"] == "messenger:ops" and relayed["candidates"] is None
    assert relayed["text_chars"] == len("relayed words")
    assert relayed["at"] == NOW
    assert _bot(response.json(), "support")["last_update_at"] == NOW


async def test_the_recent_list_is_bounded(service: TelegramService) -> None:
    for update_id in range(1, DEFAULT_RECENT_SIZE + 6):
        await service.handle_update(
            "support", message_update(update_id, chat_id=-1001, message_id=update_id)
        )
    recent = service.recent_messages()
    assert len(recent) == DEFAULT_RECENT_SIZE
    assert recent[0].message_id == DEFAULT_RECENT_SIZE + 5
    assert recent[-1].message_id == 6


async def test_a_sink_error_quoting_the_message_never_reaches_the_panel(
    app: FastAPI, service: TelegramService, vault: FakeVault, bus: RecordingBus
) -> None:
    """A sink's exception can carry what it was handed — a pydantic
    ``ValidationError`` quotes its ``input_value``. The outcome names the
    destination and the exception's type; the words stay in the hub log."""

    class Capture(BaseModel):
        size: int

    words = "the launch code is swordfish"
    # Guard the guard: the leak this test is about is real.
    with pytest.raises(ValidationError) as raised:
        Capture.model_validate({"size": words})
    assert "swordfish" in str(raised.value)

    async def refuse(**kwargs: Any) -> None:
        Capture.model_validate({"size": kwargs["content"]})

    vault.capture = refuse  # type: ignore[method-assign]
    await service.handle_update("support", message_update(1, chat_id=-1002, text=words))

    entry = service.recent_messages()[0]
    assert entry.routed is True and entry.delivered is False
    assert entry.detail == (
        "delivery to inbox:work failed (ValidationError); the hub log has the details"
    )
    assert "swordfish" not in repr(service.recent_messages())
    assert "swordfish" not in repr(bus.events)
    response = await _request(app, "GET", "/api/telegram/status")
    assert "swordfish" not in response.text


async def test_the_handled_event_follows_the_record_however_slow_the_delivery(
    service: TelegramService, vault: FakeVault
) -> None:
    """``telegram.message.received`` fires before the delivery starts; a
    panel that refetched on it alone would miss an entry whose delivery
    outlasted its debounce. ``telegram.message.handled`` is the one that
    comes after the record."""
    seen: list[tuple[str, int, dict[str, Any]]] = []
    service.publish = lambda name, data: seen.append((name, len(service.recent_messages()), data))

    async def slow_capture(**kwargs: Any) -> None:
        await asyncio.sleep(0.05)

    vault.capture = slow_capture  # type: ignore[method-assign]
    await service.handle_update("support", message_update(1, chat_id=-1002, text="slow words"))
    # Not a message: nothing recorded, nothing handled.
    await service.handle_update("support", {"update_id": 2, "callback_query": {"id": "x"}})

    assert [(name, entries) for name, entries, _ in seen] == [
        ("telegram.message.received", 0),
        ("telegram.message.handled", 1),
    ]
    handled = seen[1][2]
    assert handled["message_id"] == 1
    assert handled["routed"] is True and handled["delivered"] is True
    assert handled["destination"] == "inbox:work"
    assert "text" not in handled and "slow words" not in repr(seen)


async def test_recording_can_never_cost_a_delivery(
    api: FakeBotApi, secrets: FakeSecrets, messenger: FakeMessenger
) -> None:
    def broken_clock() -> float:
        raise RuntimeError("clock is gone")

    service = TelegramService(
        TelegramSettings.model_validate(PANEL_SETTINGS),
        api,
        secrets,
        messenger=messenger,
        now=broken_clock,
    )
    outcome = await service.handle_update("support", message_update(1, chat_id=-1001))
    assert outcome.delivered is True
    assert len(messenger.sends) == 1
    assert service.recent_messages() == []


# ------------------------------------------------------------------ check


async def test_a_check_asks_telegram_once_and_the_status_shows_it(
    app: FastAPI, api: FakeBotApi
) -> None:
    response = await _request(app, "POST", "/api/telegram/bots/support/check")
    assert response.status_code == 200
    assert response.json()["last_check"] == {
        "ok": True,
        "username": "fake_bot",
        "checked_at": NOW,
        "error": None,
    }
    assert api.get_me_calls == 1

    # Cached: every later read shows it, none of them asks Telegram again.
    for _ in range(3):
        assert _bot(await _status(app), "support")["last_check"]["ok"] is True
    assert api.get_me_calls == 1


async def test_a_refused_token_is_a_result_not_an_error(app: FastAPI, api: FakeBotApi) -> None:
    api.fail_with = TelegramApiError("getMe", "Unauthorized", status=401)
    response = await _request(app, "POST", "/api/telegram/bots/support/check")
    assert response.status_code == 200
    check = response.json()["last_check"]
    assert check["ok"] is False and check["username"] is None
    assert "401" in check["error"] and "Unauthorized" in check["error"]


async def test_a_check_without_a_stored_token_names_the_fix(
    app: FastAPI, secrets: FakeSecrets, api: FakeBotApi
) -> None:
    del secrets.values["telegram_hooked"]
    response = await _request(app, "POST", "/api/telegram/bots/hooked/check")
    assert response.status_code == 200
    check = response.json()["last_check"]
    assert check["ok"] is False
    assert "PUT /api/secrets/telegram_hooked" in check["error"]
    assert response.json()["token_stored"] is False
    assert api.get_me_calls == 0


@pytest.mark.parametrize("key", ["nope", "asleep"], ids=["unknown", "switched-off"])
async def test_an_unknown_or_switched_off_bot_is_a_404(
    app: FastAPI, api: FakeBotApi, key: str
) -> None:
    response = await _request(app, "POST", f"/api/telegram/bots/{key}/check")
    assert response.status_code == 404
    assert "is available" in response.json()["detail"]
    assert api.get_me_calls == 0
