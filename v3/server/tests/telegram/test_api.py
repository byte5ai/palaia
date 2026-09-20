"""The HTTP half of the Bot API seam (issue #411).

Everything else in this package is tested against a fake, deliberately — see
``conftest.py``. This file is the exception, because the one thing a fake
cannot check is the wire format: which URL is built, which JSON body goes
out, and how ``{"ok": false}`` is unwrapped. It runs against
``httpx.MockTransport``, so there is still no network.
"""

from __future__ import annotations

import json

import httpx
import pytest

from palaia_hub.telegram.api import DEFAULT_API_BASE, HttpBotApi, TelegramApiError

from .conftest import BOT_A_TOKEN


def api_for(handler) -> HttpBotApi:  # noqa: ANN001
    return HttpBotApi(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


@pytest.mark.anyio
async def test_the_token_goes_in_the_path_and_the_arguments_in_the_body(
    anyio_backend: str,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.read())
        return ok({"message_id": 5, "chat": {"id": -100, "type": "group"}})

    api = api_for(handler)
    await api.send_message(BOT_A_TOKEN, chat_id="-100", text="hi")
    assert seen["url"] == f"{DEFAULT_API_BASE}/bot{BOT_A_TOKEN}/sendMessage"
    assert seen["body"] == {"chat_id": "-100", "text": "hi"}
    await api.aclose()


@pytest.mark.anyio
async def test_a_reply_uses_the_current_reply_parameters_shape(anyio_backend: str) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return ok({"message_id": 6, "chat": {"id": -100, "type": "group"}})

    api = api_for(handler)
    await api.send_message(BOT_A_TOKEN, chat_id="-100", text="hi", reply_to_message_id=41)
    assert seen["body"]["reply_parameters"] == {"message_id": 41}
    await api.aclose()


@pytest.mark.anyio
async def test_a_plain_send_carries_no_reply_parameters(anyio_backend: str) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return ok({"message_id": 7, "chat": {"id": -100, "type": "group"}})

    api = api_for(handler)
    await api.send_message(BOT_A_TOKEN, chat_id="-100", text="hi")
    assert "reply_parameters" not in seen["body"]
    await api.aclose()


@pytest.mark.anyio
async def test_get_updates_passes_the_offset_timeout_and_allowed_updates(
    anyio_backend: str,
) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return ok([{"update_id": 1}, "not an update", {"update_id": 2}])

    api = api_for(handler)
    updates = await api.get_updates(
        BOT_A_TOKEN, offset=99, timeout=30, allowed_updates=("message",)
    )
    assert seen["body"] == {"offset": 99, "timeout": 30, "allowed_updates": ["message"]}
    # Non-object entries are dropped rather than crashing the poll loop.
    assert updates == [{"update_id": 1}, {"update_id": 2}]
    await api.aclose()


@pytest.mark.anyio
async def test_a_first_poll_omits_the_offset_entirely(anyio_backend: str) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.read())
        return ok([])

    api = api_for(handler)
    await api.get_updates(BOT_A_TOKEN, offset=None, timeout=30, allowed_updates=("message",))
    assert "offset" not in seen["body"]
    await api.aclose()


@pytest.mark.anyio
async def test_an_api_level_failure_becomes_a_telegram_error_naming_the_method(
    anyio_backend: str,
) -> None:
    api = api_for(
        lambda request: httpx.Response(
            400, json={"ok": False, "description": "chat not found"}
        )
    )
    with pytest.raises(TelegramApiError) as exc:
        await api.send_message(BOT_A_TOKEN, chat_id="-1", text="hi")
    assert exc.value.method == "sendMessage"
    assert exc.value.status == 400
    assert "chat not found" in str(exc.value)
    await api.aclose()


@pytest.mark.anyio
async def test_a_non_json_body_is_a_telegram_error_not_a_value_error(
    anyio_backend: str,
) -> None:
    api = api_for(lambda request: httpx.Response(502, content=b"<html>bad gateway</html>"))
    with pytest.raises(TelegramApiError) as exc:
        await api.get_me(BOT_A_TOKEN)
    assert exc.value.status == 502
    await api.aclose()


@pytest.mark.anyio
async def test_delete_message_unwraps_the_boolean_result(anyio_backend: str) -> None:
    api = api_for(lambda request: ok(True))
    assert await api.delete_message(BOT_A_TOKEN, chat_id="-1", message_id=3) is True
    await api.aclose()


@pytest.mark.anyio
async def test_a_result_of_the_wrong_shape_is_refused(anyio_backend: str) -> None:
    api = api_for(lambda request: ok("not a message object"))
    with pytest.raises(TelegramApiError):
        await api.send_message(BOT_A_TOKEN, chat_id="-1", text="hi")
    await api.aclose()


@pytest.mark.anyio
async def test_the_long_poll_read_timeout_outlives_the_poll_itself(
    anyio_backend: str,
) -> None:
    """Otherwise every quiet poll ends in a client-side timeout instead of an
    empty batch, and the connector looks broken while working perfectly."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return ok([])

    api = api_for(handler)
    await api.get_updates(BOT_A_TOKEN, offset=None, timeout=30, allowed_updates=("message",))
    timeout = seen["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["read"] > 30
    await api.aclose()
