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


# -- session directory (SPEC-402) --------------------------------------------


def test_directory_no_access_token_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enforcement, "get_access_token", lambda: None)

    assert enforcement.missing_directory_scope_error("directory_register") is None
    assert enforcement.missing_directory_scope_error("directory_list") is None


def test_directory_sufficient_scope_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["directory:write"])
    )

    assert enforcement.missing_directory_scope_error("directory_register") is None
    assert enforcement.missing_directory_scope_error("directory_deregister") is None


def test_directory_read_scoped_token_cannot_register(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acceptance criterion: 'read-scoped token cannot register'."""
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["directory:read"])
    )

    assert enforcement.missing_directory_scope_error("directory_list") is None
    assert enforcement.missing_directory_scope_error("directory_query") is None

    error = enforcement.missing_directory_scope_error("directory_register")
    assert error is not None
    assert "directory:write" in error


# -- messenger (SPEC-403) -----------------------------------------------------


def test_messenger_no_access_token_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(enforcement, "get_access_token", lambda: None)

    assert enforcement.missing_messenger_scope_error("messenger_send") is None
    assert enforcement.missing_messenger_scope_error("messenger_check") is None


def test_messenger_send_scope_allows_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["messenger:send"])
    )

    assert enforcement.missing_messenger_scope_error("messenger_send") is None
    assert enforcement.missing_messenger_scope_error("messenger_ack") is None


def test_messenger_read_scoped_token_cannot_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPEC-403 deliverable #4: "sending requires messenger:send scope"."""
    monkeypatch.setattr(
        enforcement, "get_access_token", lambda: _FakeAccessToken(["messenger:read"])
    )

    assert enforcement.missing_messenger_scope_error("messenger_check") is None
    assert enforcement.missing_messenger_scope_error("messenger_thread") is None

    error = enforcement.missing_messenger_scope_error("messenger_send")
    assert error is not None
    assert "messenger:send" in error


def test_readable_vaults_for_call_is_none_without_a_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No verifier on this mount means "every vault this validator knows" —
    the same locked-mode posture every other check here takes."""
    monkeypatch.setattr(enforcement, "get_access_token", lambda: None)

    assert enforcement.readable_vaults_for_call() is None


def test_readable_vaults_for_call_reads_the_tokens_vault_read_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        enforcement,
        "get_access_token",
        lambda: _FakeAccessToken(["vault:work:read", "vault:home:write", "messenger:send"]),
    )

    assert enforcement.readable_vaults_for_call() == frozenset({"work"})
