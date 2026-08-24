"""``missing_scope_error`` in isolation, with ``get_access_token`` mocked.

The real end-to-end path (a token actually authenticated by fastmcp, then a
tool checking its scopes) is covered by ``test_http_auth_e2e.py``; this
file isolates the decision logic itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from palaia_hub.auth import enforcement


@dataclass
class _FakeAccessToken:
    scopes: list[str] = field(default_factory=list)


def test_no_access_token_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enforcement, "get_access_token", lambda: None)

    assert enforcement.missing_scope_error("work", "write") is None
    assert enforcement.missing_scope_error("work", "delete") is None


def test_sufficient_scope_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["vault:work:write"])
    )

    assert enforcement.missing_scope_error("work", "write") is None
    assert enforcement.missing_scope_error("work", "edit") is None


def test_missing_scope_names_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["vault:work:read"])
    )

    error = enforcement.missing_scope_error("work", "write")

    assert error is not None
    assert "vault:work:write" in error


def test_read_scope_does_not_cover_a_different_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["vault:personal:read"])
    )

    error = enforcement.missing_scope_error("work", "search")

    assert error is not None
    assert "vault:work:read" in error


# -- stash (SPEC-202) --------------------------------------------------------


def test_stash_no_access_token_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enforcement, "get_access_token", lambda: None)

    assert enforcement.missing_stash_scope_error("stash_set") is None
    assert enforcement.missing_stash_scope_error("stash_get") is None


def test_stash_sufficient_scope_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["stash:write"])
    )

    assert enforcement.missing_stash_scope_error("stash_set") is None
    assert enforcement.missing_stash_scope_error("stash_del") is None


def test_stash_read_scoped_token_cannot_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance criterion: 'read-scoped token cannot write'."""
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["stash:read"])
    )

    assert enforcement.missing_stash_scope_error("stash_get") is None

    error = enforcement.missing_stash_scope_error("stash_set")
    assert error is not None
    assert "stash:write" in error
