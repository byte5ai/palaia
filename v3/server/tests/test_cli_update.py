"""SPEC-501 acceptance: "compose helper prints correct commands for the
shipped compose file" — ``palaia-hub update``, driven through the real CLI
parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.cli import main


def test_update_with_no_channel_just_prints_the_two_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("image: ghcr.io/byte5ai/palaia-hub:stable\n", encoding="utf-8")

    main(["update", "--file", str(compose)])

    out = capsys.readouterr().out
    assert "docker compose pull" in out
    assert "docker compose up -d" in out
    # No channel requested — the file is untouched.
    assert compose.read_text(encoding="utf-8") == "image: ghcr.io/byte5ai/palaia-hub:stable\n"


def test_update_with_a_channel_rewrites_the_file_and_prints_the_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("image: ghcr.io/byte5ai/palaia-hub:stable\n", encoding="utf-8")

    main(["update", "--channel", "beta", "--file", str(compose)])

    out = capsys.readouterr().out
    assert "beta" in out
    assert "docker compose pull" in out
    assert "docker compose up -d" in out
    assert compose.read_text(encoding="utf-8") == "image: ghcr.io/byte5ai/palaia-hub:beta\n"


def test_update_against_the_shipped_compose_file_prints_correct_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shipped = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"

    main(["update", "--file", str(shipped)])

    out = capsys.readouterr().out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    assert "docker compose pull" in lines
    assert "docker compose up -d" in lines
    # Read-only run (no --channel) must not have touched the real file.
    assert "image: ghcr.io/byte5ai/palaia-hub:stable" in shipped.read_text(encoding="utf-8")


def test_update_refuses_a_missing_compose_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nope.yml"
    with pytest.raises(SystemExit) as exc_info:
        main(["update", "--file", str(missing)])
    assert exc_info.value.code == 1
    assert "no compose file" in capsys.readouterr().err
