"""Webhook transport and its secret-token check (issue #411) — the other half
of the fourth acceptance criterion, and all of "webhook secret-token
verification tested".

The endpoint is unauthenticated in every other sense (Telegram is not a
browser and carries no bearer token), so the header check is the whole
credential. These tests assert it fails closed in each of the four ways it
can be wrong: absent, empty, another bot's, and merely a prefix of the real
one.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.service import TelegramService
from palaia_hub.telegram.webhook import (
    SECRET_HEADER,
    build_telegram_webhook_router,
    verify_secret,
)

from .conftest import FakeBotApi, FakeMessenger, FakeSecrets, RecordingBus, message_update

WEBHOOK_SETTINGS = {
    "bots": [
        {
            "key": "support",
            "token_secret": "telegram_support",
            "transport": "webhook",
            "webhook_secret": "telegram_support_hook",
        },
        {"key": "personal", "token_secret": "telegram_personal"},
    ],
    "routes": [
        {"bot": "support", "chat": "*", "destination": {"kind": "messenger", "to": "ops-agent"}}
    ],
}

HOOK_SECRET = "a-random-32-character-webhook-value"


@pytest.fixture
def messenger_sink() -> FakeMessenger:
    return FakeMessenger()


@pytest.fixture
def webhook_service(messenger_sink: FakeMessenger) -> TelegramService:
    return TelegramService(
        TelegramSettings.model_validate(WEBHOOK_SETTINGS),
        FakeBotApi(),
        FakeSecrets(
            {
                "telegram_support": "123456789:AAHtoken",
                "telegram_support_hook": HOOK_SECRET,
                "telegram_personal": "987654321:AAHtoken",
            }
        ),
        messenger=messenger_sink,
        publish=RecordingBus(),
    )


@pytest.fixture
def client(webhook_service: TelegramService) -> TestClient:
    app = FastAPI()
    app.include_router(build_telegram_webhook_router(webhook_service))
    return TestClient(app)


def test_a_correct_secret_token_delivers_the_update(
    client: TestClient, messenger_sink: FakeMessenger
) -> None:
    response = client.post(
        "/telegram/webhook/support",
        json=message_update(1, chat_id=-500, text="from the webhook"),
        headers={SECRET_HEADER: HOOK_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["delivered"] is True
    assert "from the webhook" in messenger_sink.sends[0]["body"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {SECRET_HEADER: ""},
        {SECRET_HEADER: "not-the-secret"},
        {SECRET_HEADER: HOOK_SECRET[:-1]},
        {SECRET_HEADER: HOOK_SECRET + "x"},
    ],
    ids=["absent", "empty", "wrong", "prefix", "extended"],
)
def test_a_bad_secret_token_is_refused_and_nothing_is_delivered(
    client: TestClient, messenger_sink: FakeMessenger, headers: dict[str, str]
) -> None:
    response = client.post(
        "/telegram/webhook/support",
        json=message_update(2, chat_id=-500),
        headers=headers,
    )
    assert response.status_code == 401
    assert messenger_sink.sends == []


def test_an_unknown_bot_is_a_404_that_names_no_other_bot(client: TestClient) -> None:
    response = client.post(
        "/telegram/webhook/ghost",
        json=message_update(3, chat_id=-500),
        headers={SECRET_HEADER: HOOK_SECRET},
    )
    assert response.status_code == 404
    assert "support" not in response.text and "personal" not in response.text


def test_a_polling_bot_has_no_webhook_endpoint(client: TestClient) -> None:
    response = client.post(
        "/telegram/webhook/personal",
        json=message_update(4, chat_id=-500),
        headers={SECRET_HEADER: HOOK_SECRET},
    )
    assert response.status_code == 404


def test_an_unstored_webhook_secret_fails_closed(messenger_sink: FakeMessenger) -> None:
    """Configured for webhooks, secret store empty: the endpoint must refuse
    rather than degrade into accepting anything."""
    service = TelegramService(
        TelegramSettings.model_validate(WEBHOOK_SETTINGS),
        FakeBotApi(),
        FakeSecrets({"telegram_support": "123456789:AAHtoken"}),
        messenger=messenger_sink,
    )
    app = FastAPI()
    app.include_router(build_telegram_webhook_router(service))
    with TestClient(app) as client:
        response = client.post(
            "/telegram/webhook/support",
            json=message_update(5, chat_id=-500),
            headers={SECRET_HEADER: HOOK_SECRET},
        )
    assert response.status_code == 503
    assert messenger_sink.sends == []


def test_a_body_that_is_not_an_update_is_a_400_not_a_crash(client: TestClient) -> None:
    response = client.post(
        "/telegram/webhook/support",
        content=b"not json",
        headers={SECRET_HEADER: HOOK_SECRET, "content-type": "application/json"},
    )
    assert response.status_code == 400


def test_an_undeliverable_update_still_answers_200(
    client: TestClient, messenger_sink: FakeMessenger
) -> None:
    """Telegram retries anything that is not a 2xx. A hub-side delivery
    failure must not turn into a redelivery loop."""

    async def boom(**kwargs: object) -> None:
        raise RuntimeError("messenger is down")

    messenger_sink.send_as_owner = boom  # type: ignore[method-assign]
    response = client.post(
        "/telegram/webhook/support",
        json=message_update(6, chat_id=-500),
        headers={SECRET_HEADER: HOOK_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["delivered"] is False


def test_an_update_matching_no_route_still_answers_200(client: TestClient) -> None:
    service_response = client.post(
        "/telegram/webhook/support",
        json={"update_id": 7, "callback_query": {"id": "x"}},
        headers={SECRET_HEADER: HOOK_SECRET},
    )
    assert service_response.status_code == 200
    assert service_response.json()["routed"] is False


def test_verify_secret_is_false_for_anything_missing() -> None:
    assert verify_secret("expected", "expected") is True
    assert verify_secret("expected", None) is False
    assert verify_secret("expected", "") is False
    assert verify_secret("", "expected") is False
    assert verify_secret("", None) is False
