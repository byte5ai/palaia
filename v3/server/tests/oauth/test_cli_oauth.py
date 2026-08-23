"""``palaia-hub oauth set-password / machine-client / clients / gc`` in-process.

The admin surface is CLI-only by design (see ``_add_oauth_parser``'s docstring
in :mod:`palaia_hub.cli`), so these are the only entry points for setting the
owner password and minting a machine identity — which makes them worth testing
as commands, not just as functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.cli import main
from palaia_hub.oauth import OAuthStore

PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(
        "mode: locked\noauth:\n  enabled: true\n  issuer: https://hub.test\n"
        "  profiles: [alpha, beta]\n",
        encoding="utf-8",
    )


def _opened(tmp_path: Path) -> OAuthStore:
    store = OAuthStore(tmp_path)
    store.open()
    return store


def test_set_password_creates_the_owner_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("palaia_hub.cli.getpass.getpass", lambda _prompt="": PASSWORD)

    main(["oauth", "set-password", "--username", "owner"])

    out = capsys.readouterr().out
    assert "owner" in out
    assert PASSWORD not in out, "the password must not be echoed back"
    store = _opened(tmp_path)
    try:
        owner = store.get_owner()
        assert owner is not None and owner[0] == "owner"
        assert owner[1].startswith("$argon2id$")
    finally:
        store.close()


def test_set_password_rejects_a_mismatched_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    answers = iter([PASSWORD, "something-else-entirely"])
    monkeypatch.setattr("palaia_hub.cli.getpass.getpass", lambda _prompt="": next(answers))

    with pytest.raises(SystemExit) as excinfo:
        main(["oauth", "set-password", "--username", "owner"])

    assert excinfo.value.code != 0


def test_set_password_rejects_a_short_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr("palaia_hub.cli.getpass.getpass", lambda _prompt="": "short")

    with pytest.raises(SystemExit) as excinfo:
        main(["oauth", "set-password", "--username", "owner"])

    assert excinfo.value.code != 0


def test_machine_client_prints_its_secret_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)

    main(
        [
            "oauth",
            "machine-client",
            "--name",
            "nightly job",
            "--profile",
            "alpha",
            "--scope",
            "vault:work:read",
        ]
    )

    out = capsys.readouterr().out
    assert "https://hub.test/alpha" in out
    assert "will not be shown again" in out
    store = _opened(tmp_path)
    try:
        clients = store.list_clients()
        assert len(clients) == 1
        assert clients[0].is_machine is True
        assert clients[0].pinned_audience == "https://hub.test/alpha"
        # Whatever was printed, only the hash is stored.
        assert clients[0].client_secret_hash is not None
        assert clients[0].client_secret_hash not in out
    finally:
        store.close()


def test_machine_client_for_an_unknown_profile_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _home(monkeypatch, tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "oauth",
                "machine-client",
                "--name",
                "job",
                "--profile",
                "nope",
                "--scope",
                "vault:work:read",
            ]
        )

    assert excinfo.value.code != 0


def test_clients_lists_what_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)
    main(["oauth", "clients"])
    assert "No registered OAuth clients yet." in capsys.readouterr().out

    main(
        [
            "oauth",
            "machine-client",
            "--name",
            "nightly job",
            "--profile",
            "alpha",
            "--scope",
            "vault:work:read",
        ]
    )
    capsys.readouterr()
    main(["oauth", "clients"])

    out = capsys.readouterr().out
    assert "machine" in out
    assert "nightly job" in out


def test_gc_runs_immediately_and_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _home(monkeypatch, tmp_path)

    main(["oauth", "gc"])

    out = capsys.readouterr().out
    assert "Pruned 0 orphaned client(s)" in out
