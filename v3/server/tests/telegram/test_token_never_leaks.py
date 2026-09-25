"""The third acceptance criterion, asserted in all three places it names
(issue #411):

    "A bot token never appears in config, logs, or tool output."

Modelled on ``tests/upstream/test_secret_never_leaks.py``, which does the
same job for upstream credentials. The three halves here are:

1. **Config** — :class:`~palaia_hub.telegram.models.TelegramBotConfig` has no
   field a token could be written into, and the model forbids extras, so a
   ``config.yaml`` that tried would be refused at load.
2. **Logs** — a Telegram token travels in the *URL path*, which none of the
   pre-existing redaction patterns look at; ``palaia_hub.logging`` gained a
   pattern for its shape, and :class:`palaia_hub.telegram.api.HttpBotApi`
   scrubs it before an error is ever raised.
3. **Tool output** — the outbound result models have no field for it, and a
   Bot API failure surfaces as a tool error built from the *method name*.

Plus the surface issue #439 added: the dashboard panel's status response,
which shows error lines and check results that started life as Bot API
failures.
"""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI

from palaia_hub.logging import REDACTED, RedactionFilter, redact
from palaia_hub.telegram.api import HttpBotApi, TelegramApiError, redact_token
from palaia_hub.telegram.dashboard_api import build_telegram_dashboard_router
from palaia_hub.telegram.models import (
    SentMessage,
    TelegramBotConfig,
    TelegramError,
    TelegramSettings,
)
from palaia_hub.telegram.runtime import TelegramRuntime
from palaia_hub.telegram.service import TelegramService

from .conftest import (
    BOT_A_TOKEN,
    BOT_B_TOKEN,
    TWO_BOT_SETTINGS,
    FakeBotApi,
    FakeSecrets,
    message_update,
)

# -- 1. config ----------------------------------------------------------------


def test_a_bot_config_has_no_field_a_token_could_live_in() -> None:
    assert "token" not in TelegramBotConfig.model_fields
    assert TelegramBotConfig.model_fields["token_secret"].annotation is str


def test_a_config_that_tries_to_carry_a_token_is_refused() -> None:
    with pytest.raises(Exception) as exc:
        TelegramSettings.model_validate(
            {"bots": [{"key": "support", "token_secret": "s", "token": BOT_A_TOKEN}]}
        )
    assert "extra" in str(exc.value).lower()


def test_a_dumped_config_contains_no_token(tmp_path) -> None:  # noqa: ANN001
    settings = TelegramSettings.model_validate(TWO_BOT_SETTINGS)
    dumped = settings.model_dump_json()
    assert BOT_A_TOKEN not in dumped
    assert "telegram_support" in dumped  # the *name*, which is fine


# -- 2. logs ------------------------------------------------------------------


def test_the_redaction_filter_masks_a_token_in_a_url_path() -> None:
    line = f"POST https://api.telegram.org/bot{BOT_A_TOKEN}/sendMessage failed"
    assert BOT_A_TOKEN not in redact(line)
    assert REDACTED in redact(line)


def test_the_redaction_filter_masks_a_bare_token() -> None:
    assert BOT_A_TOKEN not in redact(f"token was {BOT_A_TOKEN}")


def test_the_redaction_filter_leaves_ordinary_colon_text_alone() -> None:
    """The pattern keys on `<6+ digits>:<20+ token chars>`; an ordinary
    diagnostic with a colon in it must survive unredacted."""
    for line in ("status_code: 404", "elapsed 12:30", "chat -1001234567890 message 42"):
        assert redact(line) == line


def test_a_log_record_carrying_a_token_is_scrubbed_before_a_handler_sees_it() -> None:
    record = logging.LogRecord(
        name="palaia_hub.telegram.api",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="calling https://api.telegram.org/bot%s/getMe",
        args=(BOT_A_TOKEN,),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
    assert BOT_A_TOKEN not in record.getMessage()


# -- 3. tool output and errors ------------------------------------------------


def test_the_send_result_has_no_field_a_token_could_live_in() -> None:
    assert "token" not in SentMessage.model_fields


def test_an_api_error_never_quotes_the_url_it_built() -> None:
    error = TelegramApiError("sendMessage", f"connect to /bot{BOT_A_TOKEN}/sendMessage failed")
    assert BOT_A_TOKEN not in str(error)
    assert "sendMessage" in str(error)


def test_redact_token_masks_the_shape_wherever_it_appears() -> None:
    assert redact_token(f"a {BOT_A_TOKEN} b") == f"a {REDACTED} b"


@pytest.mark.anyio
async def test_a_transport_failure_does_not_leak_the_token_from_httpx(
    anyio_backend: str,
) -> None:
    """``httpx``'s own exception messages embed the request URL — which, for
    Telegram, contains the token. The client catches and re-raises rather
    than letting one through."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed to connect to {request.url}", request=request)

    transport = httpx.MockTransport(explode)
    api = HttpBotApi(client=httpx.AsyncClient(transport=transport))
    with pytest.raises(TelegramApiError) as exc:
        await api.get_me(BOT_A_TOKEN)
    assert BOT_A_TOKEN not in str(exc.value)
    await api.aclose()


@pytest.mark.anyio
async def test_an_api_description_containing_a_token_is_scrubbed(
    anyio_backend: str,
) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"ok": False, "description": f"Unauthorized: bad token {BOT_A_TOKEN}"},
        )

    api = HttpBotApi(client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    with pytest.raises(TelegramApiError) as exc:
        await api.get_me(BOT_A_TOKEN)
    assert BOT_A_TOKEN not in str(exc.value)
    assert "401" in str(exc.value)
    await api.aclose()


@pytest.mark.anyio
async def test_no_event_this_connector_emits_carries_a_token(
    anyio_backend: str,
) -> None:
    events: list[tuple[str, dict]] = []
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS),
        FakeBotApi(),
        FakeSecrets({"telegram_support": BOT_A_TOKEN, "telegram_personal": BOT_A_TOKEN}),
        publish=lambda name, data: events.append((name, data)),
    )
    await service.send(profile="default", bot="support", chat="-1001", text="hi")
    assert events
    assert BOT_A_TOKEN not in repr(events)


def test_the_service_holds_no_token_attribute() -> None:
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS),
        FakeBotApi(),
        FakeSecrets({"telegram_support": BOT_A_TOKEN}),
    )
    assert BOT_A_TOKEN not in repr(vars(service))


def test_the_http_client_holds_no_token_attribute() -> None:
    api = HttpBotApi()
    assert "token" not in vars(api)


# -- 4. the dashboard panel (issue #439) -------------------------------------


@pytest.mark.anyio
async def test_the_dashboard_status_never_carries_a_token(anyio_backend: str) -> None:
    """Every place the panel shows something that began as a failure — a
    poll error, a failed check, a failed delivery — fed a raw token, and
    the status response still has none."""
    api = FakeBotApi()
    secrets = FakeSecrets({"telegram_support": BOT_A_TOKEN, "telegram_personal": BOT_B_TOKEN})
    service = TelegramService(TelegramSettings.model_validate(TWO_BOT_SETTINGS), api, secrets)
    runtime = TelegramRuntime(service, api)

    # A plain TelegramError is not scrubbed on construction the way
    # TelegramApiError is — the panel's own scrubbing is what is under test.
    api.fail_with = TelegramError(f"getMe failed for /bot{BOT_A_TOKEN}/getMe")
    await runtime.check_bot("support")
    poller = runtime.pollers["personal"]

    async def no_sleep(seconds: float) -> None:
        return None

    poller._sleep = no_sleep  # noqa: SLF001 - skip the real backoff delay
    await poller._backoff(f"unexpected ConnectError: /bot{BOT_B_TOKEN}/getUpdates")  # noqa: SLF001
    # No messenger on this hub, so the routed message fails to deliver —
    # with the token in its text, which must not survive into the list.
    await service.handle_update(
        "support", message_update(1, chat_id=-1001, text=f"my token is {BOT_A_TOKEN}")
    )

    app = FastAPI()
    app.include_router(build_telegram_dashboard_router(runtime, secrets))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as client:
        response = await client.get("/api/telegram/status")

    assert response.status_code == 200
    body = response.json()
    assert body["bots"][0]["last_check"]["ok"] is False
    assert body["bots"][1]["polling"]["last_error"]
    assert body["recent"][0]["delivered"] is False
    assert BOT_A_TOKEN not in response.text
    assert BOT_B_TOKEN not in response.text
