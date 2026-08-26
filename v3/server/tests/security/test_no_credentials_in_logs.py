"""No credential class reaches the logs (SPEC-502 #3, acceptance #6).

SPEC-203 established the rule and tested it for its own credentials
(``tests/test_logging_redaction.py``); SPEC-302 tested it for upstream secret
*values* (``tests/upstream/test_secret_never_leaks.py``). This module is the
extension SPEC-502 asks for, over the three packages that landed since and
carry credentials or private content of their own:

* **the secret store** — the Fernet key and the ciphertext, on top of the
  plaintext value the SPEC-302 test already covers;
* **the session directory** — the per-session secret it mints once and only
  stores hashed;
* **the messenger** — envelope bodies, which are not credential-shaped and
  so cannot be caught by a redaction pattern at all: for those the property
  is that nothing logs them in the first place.

Each package is *exercised* — registered, sent, stored, failed — with the
root ``palaia_hub`` logger captured at DEBUG, and the canary is then searched
for in every record, formatted and raw.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.logging import RedactionFilter, redact
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore
from palaia_hub.upstream.secrets import SecretStore, SecretStoreError

#: Distinctive enough that a substring search cannot false-negative.
CANARY = "canary-9f3a1c-must-never-appear-in-a-log"


def _all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Every captured record, formatted the way a handler would format it."""
    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(str(record.args))
        parts.append(str(record.msg))
        if record.exc_info:
            parts.append(str(record.exc_info[1]))
    return "\n".join(parts)


@pytest.fixture(autouse=True)
def capture_everything(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="palaia_hub")


# --------------------------------------------------------------- secrets


def test_the_secret_store_logs_neither_value_nor_key_material(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = SecretStore(tmp_path)
    store.put("upstream-token", CANARY)
    assert store.get("upstream-token") == CANARY
    store.delete("upstream-token")
    key_material = (tmp_path / "secrets.key").read_text(encoding="utf-8").strip()
    store.close()

    text = _all_log_text(caplog)
    assert CANARY not in text
    assert key_material not in text


def test_a_secret_store_error_names_the_secret_not_the_value(tmp_path: Path) -> None:
    store = SecretStore(tmp_path)
    try:
        with pytest.raises(SecretStoreError) as raised:
            store.put("a name with spaces", CANARY)
        assert CANARY not in str(raised.value)
    finally:
        store.close()


def test_ciphertext_never_reaches_a_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The store logs a *length*, deliberately — never the bytes."""
    store = SecretStore(tmp_path)
    store.put("k", CANARY)
    store.close()

    row = "".join(_all_log_text(caplog))
    assert "gAAAA" not in row, "a Fernet token prefix appeared in the log"


# ------------------------------------------------------------- directory


def test_a_session_secret_never_reaches_a_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = DirectoryStore(tmp_path / "directory.db")
    try:
        record, secret, _stale = store.register(
            scope="team", host="devbox", platform="linux", agent_kind="codex", model="a-model"
        )
        store.heartbeat(record.handle, secret)
        with pytest.raises(Exception):  # noqa: B017 - any refusal, the point is the log
            store.heartbeat(record.handle, "the-wrong-secret")
    finally:
        store.close()

    assert secret not in _all_log_text(caplog)


def test_the_stored_form_of_a_session_secret_is_a_hash(tmp_path: Path) -> None:
    """A stolen database must not hand over live session credentials."""
    store = DirectoryStore(tmp_path / "directory.db")
    try:
        _record, secret, _stale = store.register(
            scope="team", host="devbox", platform="linux", agent_kind="codex", model="a-model"
        )
        raw = (tmp_path / "directory.db").read_bytes()
    finally:
        store.close()

    assert secret.encode() not in raw


# ------------------------------------------------------------- messenger


def test_an_envelope_body_never_reaches_a_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    directory_store = DirectoryStore(tmp_path / "directory.db")
    messenger_store = MessengerStore(tmp_path / "messenger.db")
    directory = DirectoryService(directory_store)
    messenger = MessengerService(messenger_store, directory)
    try:
        sender, sender_secret, _ = directory_store.register(
            scope="team", host="a", platform="linux", agent_kind="codex", model="m"
        )
        recipient, recipient_secret, _ = directory_store.register(
            scope="team", host="b", platform="linux", agent_kind="claude", model="m"
        )

        async def exchange() -> None:
            await messenger.send(
                sender=sender.handle,
                session_secret=sender_secret,
                message_type="inform",
                to=recipient.handle,
                subject="a subject",
                body=CANARY,
            )
            await messenger.check(recipient.handle, recipient_secret)

        asyncio.run(exchange())
    finally:
        messenger_store.close()
        directory_store.close()

    assert CANARY not in _all_log_text(caplog)


# ------------------------------ the filter itself, on the new credential shapes


@pytest.mark.parametrize(
    "line",
    [
        f"registering session with session_secret={CANARY}",
        f'{{"session_secret": "{CANARY}"}}',
        f"secret={CANARY}",
        f"api_key: {CANARY}",
        f"Authorization: Bearer {CANARY}",
    ],
)
def test_the_redaction_filter_masks_the_new_shapes(line: str) -> None:
    """Second line of defense: even a future careless log call is masked."""
    assert CANARY not in redact(line)
    assert "REDACTED" in redact(line)


def test_the_filter_rewrites_the_record_in_place() -> None:
    record = logging.LogRecord(
        "palaia_hub.test", logging.INFO, __file__, 1, "secret=%s", (CANARY,), None
    )
    RedactionFilter().filter(record)
    assert CANARY not in record.getMessage()
