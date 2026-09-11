"""SPEC-501 acceptance: "compose helper prints correct commands for the
shipped compose file" — the file-rewrite half. CLI-level (stdout, file
writing) is covered separately in ``test_cli_update.py``."""

from __future__ import annotations

from pathlib import Path

from palaia_hub.compose_update import DEFAULT_IMAGE, rewrite_compose_channel

_SHIPPED_COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"


def test_switching_channel_rewrites_only_the_matching_image_line() -> None:
    text = (
        f'services:\n  hub:\n    image: {DEFAULT_IMAGE}:stable\n    ports:\n      - "8420:8420"\n'
    )
    new_text, outcome = rewrite_compose_channel(text, "beta")

    assert outcome == "changed"
    assert f"image: {DEFAULT_IMAGE}:beta" in new_text
    assert f"image: {DEFAULT_IMAGE}:stable" not in new_text
    # Everything else is untouched, byte for byte.
    assert new_text.count("\n") == text.count("\n")
    assert "ports:" in new_text and '"8420:8420"' in new_text


def test_already_on_the_target_channel_reports_no_change() -> None:
    text = f"image: {DEFAULT_IMAGE}:beta\n"
    new_text, outcome = rewrite_compose_channel(text, "beta")
    assert outcome == "already"
    assert new_text == text


def test_a_different_pinned_image_is_left_alone() -> None:
    text = "image: ghcr.io/someone-else/other-app:stable\n"
    new_text, outcome = rewrite_compose_channel(text, "beta")
    assert outcome == "not_found", "not 'already' — the file was never on any channel (#371)"
    assert new_text == text


def test_comments_and_unrelated_lines_pass_through_verbatim() -> None:
    text = (
        "# a comment mentioning image: foo:bar should not match\n"
        f"    image: {DEFAULT_IMAGE}:stable\n"
        "    restart: unless-stopped\n"
    )
    new_text, outcome = rewrite_compose_channel(text, "beta")
    assert outcome == "changed"
    assert "# a comment mentioning image: foo:bar should not match" in new_text
    assert "restart: unless-stopped" in new_text


def test_the_shipped_compose_file_is_actually_rewritable() -> None:
    """Guards against the helper and the shipped file drifting apart —
    if v3/deploy/docker-compose.yml ever stops pinning DEFAULT_IMAGE, this
    fails loudly instead of the helper silently no-op'ing for every real
    user of the shipped file."""
    text = _SHIPPED_COMPOSE.read_text(encoding="utf-8")
    new_text, outcome = rewrite_compose_channel(text, "beta")
    assert outcome == "changed"
    assert f"{DEFAULT_IMAGE}:beta" in new_text


# ------------------------------------------------------------------ issue #371


def test_a_quoted_image_value_is_rewritten_and_keeps_its_quotes() -> None:
    for quote in ('"', "'"):
        text = f"    image: {quote}{DEFAULT_IMAGE}:stable{quote}\n"
        new_text, outcome = rewrite_compose_channel(text, "beta")
        assert outcome == "changed"
        assert new_text == f"    image: {quote}{DEFAULT_IMAGE}:beta{quote}\n"


def test_a_mirror_registry_is_reported_as_not_found_not_as_already_switched() -> None:
    text = "    image: mirror.example.com/byte5ai/palaia-hub:stable\n"
    new_text, outcome = rewrite_compose_channel(text, "beta")
    assert outcome == "not_found"
    assert new_text == text
