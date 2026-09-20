"""The ``telegram:`` section of ``config.yaml`` (issue #411).

Two kinds of check, and the second is the interesting one:

1. Pydantic's own — shapes, charsets, uniqueness.
2. Cross-reference consistency, run by
   :class:`palaia_hub.config.HubConfig` at load time. A route naming a bot
   that is not configured is not a crash; it is a rule that silently never
   matches, which is the single worst failure mode a routing table has. It
   is refused at the moment the operator saves the file instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from palaia_hub.config import HubConfig
from palaia_hub.telegram.models import (
    TelegramConfigError,
    TelegramSettings,
    normalise_chat_ref,
)

MINIMAL = {
    "bots": [{"key": "support", "token_secret": "telegram_support"}],
    "routes": [
        {"bot": "support", "chat": "*", "destination": {"kind": "messenger", "to": "ops"}}
    ],
}


def test_a_hub_with_no_telegram_section_has_no_connector() -> None:
    assert HubConfig().telegram is None


def test_a_minimal_section_loads() -> None:
    config = HubConfig.model_validate({"telegram": MINIMAL})
    assert config.telegram is not None
    assert config.telegram.bot("support") is not None
    assert config.telegram.poll_timeout_seconds == 30.0


def test_a_route_naming_an_unconfigured_bot_is_refused_at_load() -> None:
    with pytest.raises(ValidationError) as exc:
        HubConfig.model_validate(
            {
                "telegram": {
                    "bots": [{"key": "support", "token_secret": "s"}],
                    "routes": [
                        {
                            "bot": "personal",
                            "chat": "*",
                            "destination": {"kind": "event"},
                        }
                    ],
                }
            }
        )
    assert "personal" in str(exc.value)
    assert "nothing would ever match it" in str(exc.value)


def test_a_grant_naming_an_unconfigured_bot_is_refused_at_load() -> None:
    with pytest.raises(ValidationError) as exc:
        HubConfig.model_validate(
            {
                "telegram": {
                    "bots": [{"key": "support", "token_secret": "s"}],
                    "grants": [{"profile": "default", "bots": ["ghost"]}],
                }
            }
        )
    assert "ghost" in str(exc.value)


def test_check_consistency_is_the_same_rule_on_its_own() -> None:
    settings = TelegramSettings.model_validate(
        {
            "bots": [{"key": "support", "token_secret": "s"}],
            "routes": [
                {"bot": "personal", "chat": "*", "destination": {"kind": "event"}}
            ],
        }
    )
    with pytest.raises(TelegramConfigError):
        settings.check_consistency()


def test_two_bots_with_the_same_key_are_refused() -> None:
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate(
            {
                "bots": [
                    {"key": "support", "token_secret": "a"},
                    {"key": "support", "token_secret": "b"},
                ]
            }
        )


def test_two_routes_for_the_same_bot_and_chat_are_refused() -> None:
    with pytest.raises(ValidationError) as exc:
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [
                    {"bot": "support", "chat": "-1", "destination": {"kind": "event"}},
                    {
                        "bot": "support",
                        "chat": "-1",
                        "destination": {"kind": "messenger", "to": "x"},
                    },
                ],
            }
        )
    assert "exactly one destination" in str(exc.value)


@pytest.mark.parametrize("key", ["Support", "with space", "", "-leading", "a" * 65])
def test_a_bad_bot_key_is_a_loud_error(key: str) -> None:
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate({"bots": [{"key": key, "token_secret": "s"}]})


def test_a_webhook_bot_without_a_webhook_secret_is_refused() -> None:
    with pytest.raises(ValidationError) as exc:
        TelegramSettings.model_validate(
            {
                "bots": [
                    {"key": "support", "token_secret": "s", "transport": "webhook"}
                ]
            }
        )
    assert "setWebhook" in str(exc.value)


def test_a_messenger_destination_needs_a_recipient() -> None:
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [{"bot": "support", "chat": "*", "destination": {"kind": "messenger"}}],
            }
        )


def test_an_inbox_destination_needs_a_vault() -> None:
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [{"bot": "support", "chat": "*", "destination": {"kind": "inbox"}}],
            }
        )


def test_a_destination_field_meant_for_another_kind_is_refused() -> None:
    """Silently ignoring `to:` on an inbox route would mean an operator who
    wrote it believes traffic goes somewhere it does not."""
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [
                    {
                        "bot": "support",
                        "chat": "*",
                        "destination": {"kind": "inbox", "vault": "work", "to": "ops"},
                    }
                ],
            }
        )


def test_an_automation_destination_kind_does_not_exist() -> None:
    """Automations trigger off hub events, so `kind: event` is how a Telegram
    message fires one — documented rather than invented as a fourth kind."""
    with pytest.raises(ValidationError):
        TelegramSettings.model_validate(
            {
                "bots": [{"key": "support", "token_secret": "s"}],
                "routes": [
                    {"bot": "support", "chat": "*", "destination": {"kind": "automation"}}
                ],
            }
        )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("-1001234567890", "-1001234567890"),
        (" 42 ", "42"),
        ("@OpsRoom", "@opsroom"),
        ("*", "*"),
    ],
)
def test_chat_references_normalise_to_one_comparable_form(given: str, expected: str) -> None:
    assert normalise_chat_ref(given) == expected


@pytest.mark.parametrize("given", ["ops", "@ops", "#channel", "", "@way-too-many-symbols!"])
def test_a_chat_reference_that_could_never_match_is_refused(given: str) -> None:
    with pytest.raises(TelegramConfigError):
        normalise_chat_ref(given)


def test_a_poll_timeout_outside_telegrams_range_is_refused() -> None:
    for value in (0, -1, 61):
        with pytest.raises(ValidationError):
            TelegramSettings.model_validate({**MINIMAL, "poll_timeout_seconds": value})
