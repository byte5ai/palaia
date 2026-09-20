"""Outbound sending and its fences (issue #411), including the second
acceptance criterion:

    "An agent sends a reply through the tool; it appears in the originating
    chat, threaded to the original message."

The threading half is
:func:`test_a_reply_is_threaded_under_the_message_it_answers`; the tool half
is in ``test_tools.py``.
"""

from __future__ import annotations

import pytest

from palaia_hub.telegram.models import (
    MAX_MESSAGE_CHARS,
    MessageTooLongError,
    MissingSecretError,
    NotOurMessageError,
    NotPermittedError,
    TelegramSettings,
    UnknownBotError,
)
from palaia_hub.telegram.service import EVENT_SENT, TelegramService

from .conftest import (
    BOT_A_TOKEN,
    TWO_BOT_SETTINGS,
    FakeBotApi,
    FakeSecrets,
    RecordingBus,
)


@pytest.mark.anyio
async def test_a_send_reaches_the_api_with_the_right_bots_token(
    service: TelegramService, api: FakeBotApi
) -> None:
    sent = await service.send(profile="default", bot="support", chat="-1001", text="hi")
    assert api.sent[0]["token"] == BOT_A_TOKEN
    assert api.sent[0]["chat_id"] == "-1001"
    assert sent.chat_id == -1001
    assert sent.message_id == api.sent[0]["message_id"]


@pytest.mark.anyio
async def test_a_reply_is_threaded_under_the_message_it_answers(
    service: TelegramService, api: FakeBotApi
) -> None:
    sent = await service.send(
        profile="default", bot="support", chat="-1001", text="on it", reply_to_message_id=77
    )
    assert api.sent[0]["reply_to_message_id"] == 77
    assert sent.reply_to_message_id == 77


@pytest.mark.anyio
async def test_a_send_is_announced_on_the_bus_without_its_text(
    service: TelegramService, bus: RecordingBus
) -> None:
    await service.send(profile="default", bot="support", chat="-1001", text="private answer")
    sent = bus.named(EVENT_SENT)
    assert len(sent) == 1
    assert "text" not in sent[0]
    assert sent[0]["profile"] == "default"
    assert "private answer" not in repr(bus.events)


# -- the outbound fence -------------------------------------------------------


@pytest.mark.anyio
async def test_an_unlisted_profile_is_refused_by_name(service: TelegramService) -> None:
    """Default-deny: no grant is a refusal, not an implicit 'everything'."""
    with pytest.raises(NotPermittedError) as exc:
        await service.send(profile="scratch", bot="support", chat="-1001", text="hi")
    assert "scratch" in str(exc.value)


@pytest.mark.anyio
async def test_a_grant_narrowed_to_one_bot_refuses_the_other(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "grants": [{"profile": "default", "bots": ["support"], "chats": ["*"]}],
        }
    )
    service = TelegramService(settings, api, secrets)
    await service.send(profile="default", bot="support", chat="-1001", text="ok")
    with pytest.raises(NotPermittedError):
        await service.send(profile="default", bot="personal", chat="-1002", text="nope")


@pytest.mark.anyio
async def test_a_grant_narrowed_to_one_chat_refuses_the_others(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "grants": [{"profile": "default", "bots": ["*"], "chats": ["-1001"]}],
        }
    )
    service = TelegramService(settings, api, secrets)
    await service.send(profile="default", bot="support", chat="-1001", text="ok")
    with pytest.raises(NotPermittedError):
        await service.send(profile="default", bot="support", chat="-1002", text="nope")


@pytest.mark.anyio
async def test_an_entry_with_an_empty_list_denies_everything(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    """How a profile is switched off without deleting its entry — and the
    case where the `["*"]` field default must not quietly reappear."""
    settings = TelegramSettings.model_validate(
        {**TWO_BOT_SETTINGS, "grants": [{"profile": "default", "chats": []}]}
    )
    service = TelegramService(settings, api, secrets)
    with pytest.raises(NotPermittedError):
        await service.send(profile="default", bot="support", chat="-1001", text="hi")


@pytest.mark.anyio
async def test_an_entry_naming_only_a_profile_grants_every_configured_bot(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    settings = TelegramSettings.model_validate(
        {**TWO_BOT_SETTINGS, "grants": [{"profile": "default"}]}
    )
    service = TelegramService(settings, api, secrets)
    await service.send(profile="default", bot="support", chat="-1001", text="hi")
    await service.send(profile="default", bot="personal", chat="-1002", text="hi")
    assert len(api.sent) == 2


@pytest.mark.anyio
async def test_the_grant_is_checked_before_the_token_is_ever_read(
    service: TelegramService, secrets: FakeSecrets
) -> None:
    """A refused caller must not even cause a decrypt: nothing about the
    bot's credential should depend on an unauthorised request."""
    with pytest.raises(NotPermittedError):
        await service.send(profile="scratch", bot="support", chat="-1001", text="hi")
    assert secrets.reads == []


@pytest.mark.anyio
async def test_an_unknown_bot_is_refused_without_listing_more_than_it_must(
    service: TelegramService,
) -> None:
    with pytest.raises(UnknownBotError) as exc:
        await service.send(profile="default", bot="ghost", chat="-1001", text="hi")
    assert "ghost" in str(exc.value)


@pytest.mark.anyio
async def test_a_disabled_bot_is_unavailable(api: FakeBotApi, secrets: FakeSecrets) -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "bots": [
                {"key": "support", "token_secret": "telegram_support", "enabled": False},
                {"key": "personal", "token_secret": "telegram_personal"},
            ],
        }
    )
    service = TelegramService(settings, api, secrets)
    with pytest.raises(UnknownBotError):
        await service.send(profile="default", bot="support", chat="-1001", text="hi")


@pytest.mark.anyio
async def test_a_missing_token_names_the_secret_and_the_fix(
    api: FakeBotApi, bus: RecordingBus
) -> None:
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS), api, FakeSecrets({}), publish=bus
    )
    with pytest.raises(MissingSecretError) as exc:
        await service.send(profile="default", bot="support", chat="-1001", text="hi")
    assert "telegram_support" in str(exc.value)
    assert "config.yaml" in str(exc.value)


@pytest.mark.anyio
async def test_an_over_long_message_is_refused_with_both_numbers(
    service: TelegramService,
) -> None:
    with pytest.raises(MessageTooLongError) as exc:
        await service.send(
            profile="default", bot="support", chat="-1001", text="x" * (MAX_MESSAGE_CHARS + 1)
        )
    assert str(MAX_MESSAGE_CHARS) in str(exc.value)


@pytest.mark.anyio
async def test_an_empty_message_is_refused(service: TelegramService) -> None:
    with pytest.raises(MessageTooLongError):
        await service.send(profile="default", bot="support", chat="-1001", text="   ")


# -- edit and delete ----------------------------------------------------------


@pytest.mark.anyio
async def test_a_profile_can_edit_and_delete_what_it_sent(
    service: TelegramService, api: FakeBotApi
) -> None:
    sent = await service.send(profile="default", bot="support", chat="-1001", text="draft")
    await service.edit(
        profile="default", bot="support", chat="-1001", message_id=sent.message_id, text="final"
    )
    assert api.edited[0]["text"] == "final"
    deleted = await service.delete(
        profile="default", bot="support", chat="-1001", message_id=sent.message_id
    )
    assert deleted.deleted is True
    assert api.deleted[0]["message_id"] == sent.message_id


@pytest.mark.anyio
async def test_editing_a_message_the_hub_did_not_send_is_refused(
    service: TelegramService,
) -> None:
    """Telegram would happily let an administrating bot delete a member's
    message. That is group moderation, which is out of scope, so the fence
    is here rather than left to the remote end."""
    with pytest.raises(NotOurMessageError):
        await service.edit(
            profile="default", bot="support", chat="-1001", message_id=4321, text="nope"
        )


@pytest.mark.anyio
async def test_one_profile_cannot_edit_another_profiles_message(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "grants": [
                {"profile": "one", "bots": ["*"], "chats": ["*"]},
                {"profile": "two", "bots": ["*"], "chats": ["*"]},
            ],
        }
    )
    service = TelegramService(settings, api, secrets)
    sent = await service.send(profile="one", bot="support", chat="-1001", text="mine")
    with pytest.raises(NotPermittedError) as exc:
        await service.edit(
            profile="two", bot="support", chat="-1001", message_id=sent.message_id, text="theirs"
        )
    assert "'one'" in str(exc.value)


@pytest.mark.anyio
async def test_a_deleted_message_is_forgotten_so_a_second_delete_is_refused(
    service: TelegramService,
) -> None:
    sent = await service.send(profile="default", bot="support", chat="-1001", text="oops")
    await service.delete(
        profile="default", bot="support", chat="-1001", message_id=sent.message_id
    )
    with pytest.raises(NotOurMessageError):
        await service.delete(
            profile="default", bot="support", chat="-1001", message_id=sent.message_id
        )


@pytest.mark.anyio
async def test_a_channel_addressed_by_name_can_be_edited_through_the_same_name(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    """A send to ``@ops`` teaches the ledger which numeric id that is, so an
    agent does not have to carry the id back to edit."""
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "grants": [{"profile": "default", "bots": ["*"], "chats": ["@opsroom"]}],
        }
    )
    service = TelegramService(settings, api, secrets)
    sent = await service.send(profile="default", bot="support", chat="@opsroom", text="hello")
    await service.edit(
        profile="default",
        bot="support",
        chat="@OPSROOM",
        message_id=sent.message_id,
        text="hello again",
    )
    assert api.edited[0]["chat_id"] == "@opsroom"


@pytest.mark.anyio
async def test_the_ledger_is_bounded(api: FakeBotApi, secrets: FakeSecrets) -> None:
    service = TelegramService(
        TelegramSettings.model_validate(TWO_BOT_SETTINGS), api, secrets, ledger_capacity=3
    )
    for _ in range(10):
        await service.send(profile="default", bot="support", chat="-1001", text="spam")
    assert len(service.ledger) == 3


# -- what an agent can see ----------------------------------------------------


def test_list_chats_shows_routes_and_whether_this_profile_may_send(
    service: TelegramService,
) -> None:
    rows = {(row.bot, row.chat): row for row in service.list_chats("default")}
    assert rows[("support", "-1001")].destination == "messenger:ops-agent"
    assert rows[("personal", "-1002")].destination == "inbox:work"
    assert all(row.can_send for row in rows.values())


def test_list_chats_marks_a_route_this_profile_may_not_send_to(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "grants": [{"profile": "readonly", "bots": ["support"], "chats": ["-1001"]}],
        }
    )
    service = TelegramService(settings, api, secrets)
    rows = {(row.bot, row.chat): row for row in service.list_chats("readonly")}
    assert rows[("support", "-1001")].can_send is True
    assert rows[("personal", "-1002")].can_send is False


def test_list_chats_is_empty_for_a_profile_with_no_grant_and_no_routes(
    api: FakeBotApi, secrets: FakeSecrets
) -> None:
    service = TelegramService(
        TelegramSettings.model_validate({"bots": [], "routes": [], "grants": []}), api, secrets
    )
    assert service.list_chats("default") == []
