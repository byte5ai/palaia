"""``palaia-hub curator run/apply/token`` in-process (SPEC-206 deliverable #1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.auth.store import TokenStore
from palaia_hub.cli import main
from palaia_hub.curator.profile import CURATOR_PROFILE_PATH
from palaia_hub.curator.wiring import TOKEN_ENV


def test_curator_token_is_bound_to_the_curator_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))

    main(["curator", "token"])

    out = capsys.readouterr().out
    assert TOKEN_ENV in out
    assert "plt_" in out
    [info] = TokenStore(tmp_path).list_tokens()
    assert info.profile == CURATOR_PROFILE_PATH
    assert info.name == "curator"


def test_curator_run_on_a_hub_with_no_vaults_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))

    main(["curator", "run"])

    assert "No vaults to curate" in capsys.readouterr().out


def test_curator_run_reports_an_empty_inbox_per_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PALAIA_HOME", str(tmp_path))
    from palaia_hub.vault import VaultRegistry

    registry = VaultRegistry(tmp_path)
    import asyncio

    asyncio.run(_create_vault(registry, tmp_path))

    main(["curator", "run"])

    out = capsys.readouterr().out
    assert "work: inbox empty, no session started." in out

    main(["curator", "apply", "--json"])
    assert '"approved": 0' in capsys.readouterr().out


async def _create_vault(registry: object, tmp_path: Path) -> None:
    engine = await registry.create(  # type: ignore[attr-defined]
        "work", tmp_path / "vaults" / "work", purpose="CLI test vault."
    )
    await engine.close()
