"""Scope classification for the stash tool family (SPEC-202) — same
treatment as ``test_scopes.py`` gives the memory tool family."""

from __future__ import annotations

from palaia_hub.auth.scopes import (
    STASH_READ_ACTIONS,
    STASH_WRITE_ACTIONS,
    required_scope_for_stash_action,
    stash_scope,
)
from palaia_hub.gateway.stash_tools import STASH_TOOL_ACTIONS


def test_stash_scope_format() -> None:
    assert stash_scope("read") == "stash:read"
    assert stash_scope("write") == "stash:write"


def test_every_stash_action_is_classified_exactly_once() -> None:
    assert STASH_READ_ACTIONS & STASH_WRITE_ACTIONS == frozenset()
    assert frozenset(STASH_TOOL_ACTIONS) == STASH_READ_ACTIONS | STASH_WRITE_ACTIONS


def test_read_actions_require_read_scope() -> None:
    for action in STASH_READ_ACTIONS:
        assert required_scope_for_stash_action(action) == "stash:read"


def test_write_actions_require_write_scope() -> None:
    for action in STASH_WRITE_ACTIONS:
        assert required_scope_for_stash_action(action) == "stash:write"


def test_unknown_action_fails_closed_to_write() -> None:
    assert required_scope_for_stash_action("some_future_action") == "stash:write"
