"""Routing by origin (issue #411), including the first acceptance criterion:

    "Two bots configured; a message to bot A in chat X and a message to bot B
    in chat Y arrive at two different configured destinations."

That one is :func:`test_two_bots_two_chats_land_in_two_different_destinations`
below, asserted end to end through the service against the fake Bot API.
"""

from __future__ import annotations

import pytest

from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.routing import RoutingTable
from palaia_hub.telegram.service import EVENT_DROPPED, EVENT_RECEIVED, EVENT_ROUTED, TelegramService

from .conftest import (
    FakeBotApi,
    FakeMessenger,
    FakeSecrets,
    FakeVault,
    RecordingBus,
    message_update,
)


def table(*rules: tuple[str, str]) -> RoutingTable:
    return RoutingTable(
        TelegramSettings.model_validate(
            {
                "bots": [{"key": bot, "token_secret": f"s_{bot}"} for bot in {r[0] for r in rules}],
                "routes": [
                    {
                        "bot": bot,
                        "chat": chat,
                        "destination": {"kind": "event", "label": f"{bot}:{chat}"},
                    }
                    for bot, chat in rules
                ],
            }
        ).routes
    )


def test_the_exact_chat_id_beats_the_username_and_the_wildcard() -> None:
    routes = table(("support", "-1001"), ("support", "@opsroom"), ("support", "*"))
    message = _message(chat_id=-1001, username="opsroom")
    resolved = routes.resolve(message)
    assert resolved is not None and resolved.chat == "-1001"


def test_the_username_beats_the_wildcard() -> None:
    routes = table(("support", "@opsroom"), ("support", "*"))
    resolved = routes.resolve(_message(chat_id=-1001, username="opsroom"))
    assert resolved is not None and resolved.chat == "@opsroom"


def test_the_wildcard_catches_whatever_is_left() -> None:
    routes = table(("support", "*"))
    resolved = routes.resolve(_message(chat_id=-9999, username=None))
    assert resolved is not None and resolved.chat == "*"


def test_config_order_does_not_decide_the_winner() -> None:
    """Specificity decides, not file order — otherwise appending a catch-all
    to the bottom of config.yaml and putting it at the top would deliver
    differently, which is a trap rather than a feature."""
    specific_first = table(("support", "-1001"), ("support", "*"))
    wildcard_first = table(("support", "*"), ("support", "-1001"))
    message = _message(chat_id=-1001, username=None)
    assert specific_first.resolve(message).chat == wildcard_first.resolve(message).chat == "-1001"


def test_a_wildcard_never_reaches_across_bots() -> None:
    """The whole point of the (bot, chat) key: 'personal' having a catch-all
    must not swallow traffic that arrived through 'support'."""
    routes = table(("personal", "*"))
    assert routes.resolve(_message(chat_id=-1001, username=None, bot="support")) is None


def test_the_username_match_is_case_insensitive() -> None:
    routes = table(("support", "@opsroom"))
    assert routes.resolve(_message(chat_id=-1, username="OPSROOM")) is not None


def _message(*, chat_id: int, username: str | None, bot: str = "support"):  # noqa: ANN202
    from palaia_hub.telegram.updates import normalise_update

    message = normalise_update(
        bot, message_update(1, chat_id=chat_id, chat_username=username)
    )
    assert message is not None
    return message


# -- the acceptance criterion, end to end -------------------------------------


@pytest.mark.anyio
async def test_two_bots_two_chats_land_in_two_different_destinations(
    service: TelegramService,
    messenger: FakeMessenger,
    vault: FakeVault,
) -> None:
    support = await service.handle_update("support", message_update(1, chat_id=-1001, text="A"))
    personal = await service.handle_update("personal", message_update(2, chat_id=-1002, text="B"))

    assert support.routed and support.delivered
    assert personal.routed and personal.delivered
    assert support.destination == "messenger:ops-agent"
    assert personal.destination == "inbox:work"

    assert len(messenger.sends) == 1
    assert messenger.sends[0]["to"] == "ops-agent"
    assert "A" in messenger.sends[0]["body"]

    assert len(vault.captures) == 1
    assert "B" in vault.captures[0]["content"]
    assert vault.captures[0]["source"] == "telegram:personal/-1002#1"


@pytest.mark.anyio
async def test_the_same_chat_id_on_the_other_bot_does_not_cross_over(
    service: TelegramService, messenger: FakeMessenger, vault: FakeVault
) -> None:
    """Chat -1001 is routed for 'support' only. The same id arriving through
    'personal' must not be delivered to the support destination."""
    outcome = await service.handle_update("personal", message_update(3, chat_id=-1001))
    assert outcome.routed is False
    assert messenger.sends == [] and vault.captures == []


@pytest.mark.anyio
async def test_an_unrouted_message_says_which_rules_would_have_matched(
    service: TelegramService, bus: RecordingBus
) -> None:
    outcome = await service.handle_update(
        "support", message_update(4, chat_id=-4242, chat_username="newroom")
    )
    assert outcome.routed is False
    dropped = bus.named(EVENT_DROPPED)
    assert dropped and dropped[0]["candidates"] == ["-4242", "@newroom", "*"]
    assert "-4242" in outcome.detail and "@newroom" in outcome.detail


@pytest.mark.anyio
async def test_every_inbound_message_is_announced_without_its_text(
    service: TelegramService, bus: RecordingBus
) -> None:
    await service.handle_update("support", message_update(5, chat_id=-1001, text="confidential"))
    received = bus.named(EVENT_RECEIVED)
    assert len(received) == 1
    assert "text" not in received[0]
    assert "confidential" not in repr(bus.events)


@pytest.mark.anyio
async def test_only_an_event_route_puts_the_text_on_the_bus(
    secrets: FakeSecrets, api: FakeBotApi, bus: RecordingBus
) -> None:
    """The one documented exception, asserted as such: an operator gets the
    message text on the bus by writing `kind: event`, and no other way."""
    service = TelegramService(
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [
                    {
                        "bot": "support",
                        "chat": "*",
                        "destination": {"kind": "event", "label": "ops"},
                    }
                ],
            }
        ),
        api,
        secrets,
        publish=bus,
    )
    outcome = await service.handle_update("support", message_update(6, chat_id=-1, text="hello"))
    assert outcome.delivered
    routed = bus.named(EVENT_ROUTED)
    assert routed == [
        {**routed[0], "label": "ops", "text": "hello"}
    ]  # the label and the text are both there
    assert bus.named(EVENT_RECEIVED)[0].get("text") is None
