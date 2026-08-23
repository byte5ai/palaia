"""``palaia-hub token create/list/revoke`` in-process (no subprocess needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.cli import main


def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    main(argv)


def test_create_prints_plaintext_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(
        monkeypatch,
        tmp_path,
        ["token", "create", "--name", "Codex on devbox", "--profile", "default"],
    )

    out = capsys.readouterr().out
    assert "Codex on devbox" in out
    assert "plt_" in out


def test_list_shows_created_tokens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _run(
        monkeypatch,
        tmp_path,
        ["token", "create", "--name", "client-a", "--profile", "default"],
    )

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        _run(monkeypatch, tmp_path, ["token", "list"])

    assert "client-a" in buf.getvalue()
    assert "active" in buf.getvalue()


def test_revoke_marks_token_revoked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from palaia_hub.auth.store import TokenStore

    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    store = TokenStore(home=tmp_path)
    created = store.create("client-a", "default", [])
    del store  # force a fresh load from disk, like a separate CLI invocation would

    main(["token", "revoke", created.info.id])

    reloaded = TokenStore(home=tmp_path)
    assert reloaded.verify(created.token) is None


def test_revoke_unknown_id_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))

    with pytest.raises(SystemExit) as excinfo:
        main(["token", "revoke", "does-not-exist"])

    assert excinfo.value.code != 0
