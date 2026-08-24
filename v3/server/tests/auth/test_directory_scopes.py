"""Scope classification for the session directory tool family (SPEC-402) —
same treatment as ``test_stash_scopes.py`` gives stash."""

from __future__ import annotations

from palaia_hub.auth.scopes import (
    DIRECTORY_READ_ACTIONS,
    DIRECTORY_WRITE_ACTIONS,
    directory_scope,
    required_scope_for_directory_action,
)
from palaia_hub.gateway.directory_tools import DIRECTORY_TOOL_ACTIONS


def test_directory_scope_format() -> None:
    assert directory_scope("read") == "directory:read"
    assert directory_scope("write") == "directory:write"


def test_every_directory_action_is_classified_exactly_once() -> None:
    assert DIRECTORY_READ_ACTIONS & DIRECTORY_WRITE_ACTIONS == frozenset()
    assert frozenset(DIRECTORY_TOOL_ACTIONS) == DIRECTORY_READ_ACTIONS | DIRECTORY_WRITE_ACTIONS


def test_read_actions_require_read_scope() -> None:
    for action in DIRECTORY_READ_ACTIONS:
        assert required_scope_for_directory_action(action) == "directory:read"


def test_write_actions_require_write_scope() -> None:
    for action in DIRECTORY_WRITE_ACTIONS:
        assert required_scope_for_directory_action(action) == "directory:write"


def test_unknown_action_fails_closed_to_write() -> None:
    assert required_scope_for_directory_action("some_future_action") == "directory:write"
