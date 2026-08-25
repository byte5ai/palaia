"""Scope classification for the messenger tool family (SPEC-403) — same
treatment as ``test_directory_scopes.py`` gives the directory, plus the
``readable_vault_keys`` helper the messenger uses to bound its ``refs``
validation."""

from __future__ import annotations

from palaia_hub.auth.scopes import (
    MESSENGER_READ_ACTIONS,
    MESSENGER_SEND_ACTIONS,
    messenger_scope,
    readable_vault_keys,
    required_scope_for_messenger_action,
)
from palaia_hub.gateway.messenger_tools import MESSENGER_TOOL_ACTIONS


def test_messenger_scope_format() -> None:
    assert messenger_scope("read") == "messenger:read"
    assert messenger_scope("send") == "messenger:send"


def test_every_messenger_action_is_classified_exactly_once() -> None:
    assert MESSENGER_READ_ACTIONS & MESSENGER_SEND_ACTIONS == frozenset()
    assert (
        frozenset(MESSENGER_TOOL_ACTIONS) == MESSENGER_READ_ACTIONS | MESSENGER_SEND_ACTIONS
    )


def test_sending_requires_the_send_scope_the_spec_names() -> None:
    assert required_scope_for_messenger_action("messenger_send") == "messenger:send"


def test_read_actions_require_the_read_scope() -> None:
    for action in MESSENGER_READ_ACTIONS:
        assert required_scope_for_messenger_action(action) == "messenger:read"


def test_ack_takes_the_stronger_scope_because_it_mutates() -> None:
    assert required_scope_for_messenger_action("messenger_ack") == "messenger:send"


def test_unknown_action_fails_closed_to_send() -> None:
    assert required_scope_for_messenger_action("some_future_action") == "messenger:send"


# -- readable_vault_keys ------------------------------------------------------


def test_readable_vault_keys_picks_out_read_scopes() -> None:
    assert readable_vault_keys(
        ["vault:work:read", "vault:home:write", "messenger:send", "stash:read"]
    ) == frozenset({"work"})


def test_write_scope_alone_does_not_imply_read() -> None:
    assert readable_vault_keys(["vault:work:write"]) == frozenset()


def test_malformed_scopes_are_ignored_rather_than_guessed_at() -> None:
    assert readable_vault_keys(["vault::read", "vault:read", "", "vault:a:b:read"]) == (
        frozenset()
    )


def test_no_scopes_is_no_readable_vaults() -> None:
    assert readable_vault_keys([]) == frozenset()
