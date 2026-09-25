"""Shared fakes for the Telegram connector tests (issue #411).

There is no sandbox Telegram and no test bot token, so the Bot API is faked
rather than reached — which is the right trade even if there were one: every
property worth asserting here (routing by origin, the outbound grant, offset
handling, webhook verification, the token never leaking) is hub-side logic,
and hub-side logic is what a fake exercises honestly. What the fake cannot
prove is that the wire format is right; that is
:class:`palaia_hub.telegram.api.HttpBotApi`'s three-line job, covered
separately in ``test_api.py`` against a stubbed httpx transport.

Every fake here records what it was given, including **the token**, so a test
can assert both that the right one was used and that it never reached a log
line, an event or a tool result.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.service import TelegramService

#: A token shaped exactly like a real one, so the redaction tests are
#: testing the real pattern and not a placeholder that happens to differ.
BOT_A_TOKEN = "123456789:AAHfake-token-for-bot-a-abcdefghijklmn"
BOT_B_TOKEN = "987654321:AAHfake-token-for-bot-b-opqrstuvwxyz0"


class FakeSecrets:
    """A :class:`palaia_hub.telegram.service.SecretReader` over a dict."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.reads: list[str] = []

    def get(self, name: str) -> str | None:
        self.reads.append(name)
        return self.values.get(name)

    def has(self, name: str) -> bool:
        """The dashboard panel's presence check (issue #439) — deliberately
        not recorded in :attr:`reads`, which counts *value* reads."""
        return name in self.values


class FakeBotApi:
    """A :class:`palaia_hub.telegram.api.BotApi` backed by scripted batches.

    ``queue`` is a list of ``getUpdates`` results, consumed one call at a
    time; an exhausted queue answers with an empty batch, which is what the
    real API does when nothing has happened.

    ``park_when_empty`` makes an exhausted queue behave like the real long
    poll instead: the call waits (until cancelled) rather than returning at
    once. That is what a test running the poller as a background task wants
    — otherwise the loop spins through empty batches for as long as the test
    runs — and it is exactly the state the hub's shutdown has to cancel.
    """

    def __init__(
        self,
        queue: list[list[dict[str, Any]]] | None = None,
        *,
        park_when_empty: bool = False,
    ) -> None:
        self.queue = list(queue or [])
        self.park_when_empty = park_when_empty
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.deleted: list[dict[str, Any]] = []
        self.get_updates_calls: list[dict[str, Any]] = []
        self.next_message_id = 1000
        self.fail_with: Exception | None = None
        #: How many ``getUpdates`` calls are (or were) parked in the long
        #: poll, and how many of those were cancelled there.
        self.parked_polls = 0
        self.cancelled_polls = 0
        #: Set by :meth:`aclose` — the one thing an owning runtime calls.
        self.closed = False
        #: How many connection checks reached "Telegram" (issue #439).
        self.get_me_calls = 0

    async def get_updates(
        self, token: str, *, offset: int | None, timeout: float, allowed_updates: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        self.get_updates_calls.append(
            {
                "token": token,
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": allowed_updates,
            }
        )
        # A real getUpdates is a long poll and always yields to the event
        # loop; this one would otherwise return without ever suspending,
        # which turns `LongPoller.run_forever` into a task that starves
        # everything else in the loop (including the test that stops it).
        await asyncio.sleep(0)
        if self.fail_with is not None:
            raise self.fail_with
        if self.queue:
            return self.queue.pop(0)
        if self.park_when_empty:
            self.parked_polls += 1
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled_polls += 1
                raise
        return []

    async def aclose(self) -> None:
        self.closed = True

    async def send_message(
        self,
        token: str,
        *,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        if self.fail_with is not None:
            raise self.fail_with
        self.next_message_id += 1
        self.sent.append(
            {
                "token": token,
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
                "message_id": self.next_message_id,
            }
        )
        numeric = int(chat_id) if chat_id.lstrip("-").isdigit() else -100999
        return {
            "message_id": self.next_message_id,
            "chat": {"id": numeric, "type": "supergroup"},
            "text": text,
        }

    async def edit_message_text(
        self, token: str, *, chat_id: str, message_id: int, text: str
    ) -> dict[str, Any]:
        self.edited.append(
            {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text}
        )
        numeric = int(chat_id) if chat_id.lstrip("-").isdigit() else -100999
        return {"message_id": message_id, "chat": {"id": numeric, "type": "supergroup"}}

    async def delete_message(self, token: str, *, chat_id: str, message_id: int) -> bool:
        self.deleted.append({"token": token, "chat_id": chat_id, "message_id": message_id})
        return True

    async def get_me(self, token: str) -> dict[str, Any]:
        self.get_me_calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        return {"id": 42, "username": "fake_bot", "is_bot": True}


class FakeMessenger:
    """A :class:`palaia_hub.telegram.service.MessengerSink` that records."""

    def __init__(self) -> None:
        self.sends: list[dict[str, Any]] = []

    async def send_as_owner(self, **kwargs: Any) -> dict[str, Any]:
        self.sends.append(kwargs)
        return {"ok": True}


class FakeVault:
    """A :class:`palaia_hub.telegram.service.InboxSink` that records."""

    def __init__(self) -> None:
        self.captures: list[dict[str, Any]] = []

    async def capture(self, **kwargs: Any) -> dict[str, Any]:
        self.captures.append(kwargs)
        return {"ok": True}


class RecordingBus:
    """The hub event hook, as a list of ``(event, data)`` pairs."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))

    def named(self, event: str) -> list[dict[str, Any]]:
        return [data for name, data in self.events if name == event]


def message_update(
    update_id: int,
    *,
    chat_id: int,
    text: str = "hello",
    message_id: int = 1,
    chat_type: str = "supergroup",
    chat_title: str | None = "Ops",
    chat_username: str | None = None,
    key: str = "message",
) -> dict[str, Any]:
    """One raw Telegram update carrying a message, in the shape the API sends."""
    chat: dict[str, Any] = {"id": chat_id, "type": chat_type}
    if chat_title:
        chat["title"] = chat_title
    if chat_username:
        chat["username"] = chat_username
    return {
        "update_id": update_id,
        key: {
            "message_id": message_id,
            "date": 1_700_000_000,
            "chat": chat,
            "from": {"id": 7, "username": "ada", "first_name": "Ada", "last_name": "Lovelace"},
            "text": text,
        },
    }


TWO_BOT_SETTINGS: dict[str, Any] = {
    "bots": [
        {"key": "support", "token_secret": "telegram_support"},
        {"key": "personal", "token_secret": "telegram_personal"},
    ],
    "routes": [
        {
            "bot": "support",
            "chat": "-1001",
            "destination": {"kind": "messenger", "to": "ops-agent"},
        },
        {
            "bot": "personal",
            "chat": "-1002",
            "destination": {"kind": "inbox", "vault": "work"},
        },
    ],
    "grants": [{"profile": "default", "bots": ["*"], "chats": ["*"]}],
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def secrets() -> FakeSecrets:
    return FakeSecrets(
        {"telegram_support": BOT_A_TOKEN, "telegram_personal": BOT_B_TOKEN}
    )


@pytest.fixture
def api() -> FakeBotApi:
    return FakeBotApi()


@pytest.fixture
def bus() -> RecordingBus:
    return RecordingBus()


@pytest.fixture
def messenger() -> FakeMessenger:
    return FakeMessenger()


@pytest.fixture
def vault() -> FakeVault:
    return FakeVault()


@pytest.fixture
def service(
    secrets: FakeSecrets,
    api: FakeBotApi,
    bus: RecordingBus,
    messenger: FakeMessenger,
    vault: FakeVault,
) -> TelegramService:
    """The two-bot hub the issue's first acceptance criterion describes."""
    return TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS),
        api,
        secrets,
        messenger=messenger,
        vaults={"work": vault},
        publish=bus,
    )
