"""Scope string composition and the read/write action classification."""

from __future__ import annotations

from palaia_hub.auth.scopes import (
    READ_ACTIONS,
    WRITE_ACTIONS,
    required_scope_for_action,
    vault_scope,
)
from palaia_hub.gateway.vault_protocol import MEMORY_TOOL_ACTIONS, RECALL_TOOL_ACTIONS


def test_vault_scope_format() -> None:
    assert vault_scope("work", "read") == "vault:work:read"
    assert vault_scope("work", "write") == "vault:work:write"


def test_every_memory_tool_action_is_classified_exactly_once() -> None:
    # No overlap, and together they cover every action the gateway exposes
    # (MEMORY_TOOL_ACTIONS is the gateway's own single source of truth for
    # "what actions exist" — see palaia_hub.gateway.vault_protocol).
    assert READ_ACTIONS & WRITE_ACTIONS == frozenset()
    assert frozenset(MEMORY_TOOL_ACTIONS) <= READ_ACTIONS | WRITE_ACTIONS


def test_recall_actions_are_classified_read_only() -> None:
    # SPEC-106's two tools answer from the vault and never write to it, so
    # a read-scoped token must be able to call them (see the comment on
    # READ_ACTIONS about the access counter).
    assert frozenset(RECALL_TOOL_ACTIONS) <= READ_ACTIONS
    for action in RECALL_TOOL_ACTIONS:
        assert required_scope_for_action("work", action) == "vault:work:read"


def test_read_actions_require_read_scope() -> None:
    for action in READ_ACTIONS:
        assert required_scope_for_action("work", action) == "vault:work:read"


def test_write_actions_require_write_scope() -> None:
    for action in WRITE_ACTIONS:
        assert required_scope_for_action("work", action) == "vault:work:write"


def test_unknown_action_fails_closed_to_write() -> None:
    assert required_scope_for_action("work", "some_future_action") == "vault:work:write"
