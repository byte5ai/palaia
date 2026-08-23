import logging
from pathlib import Path

import pytest

from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig
from palaia_hub.logging import redact, setup_logging

SECRET = "sk-abcdef1234567890"  # noqa: S105 - test fixture, not a real credential


@pytest.mark.parametrize(
    "message",
    [
        f"Authorization: Bearer {SECRET}",
        f"calling gateway with Bearer {SECRET} attached",
        f"token={SECRET}",
        f'token="{SECRET}"',
        f"api_key: {SECRET}",
        f"secret={SECRET}",
        f"password={SECRET}",
    ],
)
def test_redact_masks_known_secret_shapes(message: str) -> None:
    redacted = redact(message)

    assert SECRET not in redacted
    assert "REDACTED" in redacted


def test_redact_leaves_ordinary_text_untouched() -> None:
    message = "hub started on 127.0.0.1:8420 in locked mode"

    assert redact(message) == message


def test_logging_output_redacts_token_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(HubConfig(log_format="human"))
    logger = logging.getLogger("palaia_hub.test")

    logger.info("sending request with token=%s", SECRET)

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert "REDACTED" in captured.out


def test_logging_json_format_redacts_token(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(HubConfig(log_format="json"))
    logger = logging.getLogger("palaia_hub.test.json")

    logger.info("Authorization: Bearer %s", SECRET)

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert "REDACTED" in captured.out


# --- SPEC-108: the redaction filter covers real palaia client tokens too --


def test_real_palaia_token_is_redacted_in_bearer_form() -> None:
    token = "plt_AbCdEfGh12.zzZZzz09-_aaaBBBcccDDDeeeFFFggg1234567"
    message = f"Authorization: Bearer {token}"

    redacted = redact(message)

    assert token not in redacted
    assert "REDACTED" in redacted


def test_token_store_never_logs_the_plaintext_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="palaia_hub.auth.store")
    store = TokenStore(home=tmp_path)

    created = store.create("Codex on devbox", "default", ["vault:work:read"])
    store.revoke(created.info.id)

    secret_half = created.token.split(".", 1)[1]
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert created.token not in log_text
    assert secret_half not in log_text


def test_component_level_override(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(HubConfig(log_level="warning"), component_levels={"vault": "debug"})

    default_logger = logging.getLogger("palaia_hub.other")
    vault_logger = logging.getLogger("palaia_hub.vault")

    default_logger.debug("should not appear")
    vault_logger.debug("should appear because vault is at debug")

    captured = capsys.readouterr()
    assert "should not appear" not in captured.out
    assert "should appear because vault is at debug" in captured.out
