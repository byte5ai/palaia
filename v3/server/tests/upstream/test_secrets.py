"""SPEC-302 deliverable #2 / acceptance criterion #2: the secret store.

Covers the fixed design point by point: file modes, ``O_CREAT|O_EXCL``
creation, encryption at rest, the names-only listing, read-back across a
"restart" (a second :class:`SecretStore` over the same home), and that no
log line produced while storing or reading a secret contains its value.
"""

from __future__ import annotations

import logging
import sqlite3
import stat
from pathlib import Path

import pytest

from palaia_hub.upstream.secrets import (
    SECRETS_DB_NAME,
    SECRETS_KEY_NAME,
    SecretInfo,
    SecretStore,
    SecretStoreError,
    validate_secret_name,
)

SECRET = "sk-live-do-not-log-me-4711"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_key_and_db_files_are_0600_in_a_0700_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = SecretStore(home)
    try:
        store.put("linear-token", SECRET)
    finally:
        store.close()

    assert _mode(home) == 0o700
    assert _mode(home / SECRETS_KEY_NAME) == 0o600
    assert _mode(home / SECRETS_DB_NAME) == 0o600


def test_widened_modes_are_narrowed_again_on_the_next_open(tmp_path: Path) -> None:
    home = tmp_path / "home"
    SecretStore(home).close()
    (home / SECRETS_KEY_NAME).chmod(0o644)
    home.chmod(0o755)

    SecretStore(home).close()

    assert _mode(home / SECRETS_KEY_NAME) == 0o600
    assert _mode(home) == 0o700


def test_an_existing_key_is_never_overwritten(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = SecretStore(home)
    store.put("token", SECRET)
    store.close()
    key_before = (home / SECRETS_KEY_NAME).read_bytes()

    reopened = SecretStore(home)
    try:
        # Same key, so the value still decrypts — the O_CREAT|O_EXCL path
        # was not taken a second time.
        assert reopened.get("token") == SECRET
    finally:
        reopened.close()
    assert (home / SECRETS_KEY_NAME).read_bytes() == key_before


def test_the_value_is_encrypted_at_rest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = SecretStore(home)
    try:
        store.put("token", SECRET)
    finally:
        store.close()

    # The raw database bytes must not contain the plaintext anywhere.
    assert SECRET.encode() not in (home / SECRETS_DB_NAME).read_bytes()
    connection = sqlite3.connect(home / SECRETS_DB_NAME)
    try:
        stored = connection.execute("SELECT ciphertext FROM secrets").fetchone()[0]
    finally:
        connection.close()
    assert SECRET.encode() not in bytes(stored)


def test_put_get_delete_and_names_only_listing(secret_store: SecretStore) -> None:
    secret_store.put("b-token", "value-b")
    secret_store.put("a-token", SECRET)

    assert [info.name for info in secret_store.names()] == ["a-token", "b-token"]
    # The listing shape has no value field at all — there is nowhere to leak.
    assert set(SecretInfo.__slots__) == {"name", "created_at", "updated_at"}
    assert secret_store.get("a-token") == SECRET
    assert secret_store.get("nope") is None

    assert secret_store.delete("a-token") is True
    assert secret_store.delete("a-token") is False
    assert [info.name for info in secret_store.names()] == ["b-token"]


def test_replacing_a_value_keeps_the_created_timestamp(secret_store: SecretStore) -> None:
    first = secret_store.put("token", "one")
    second = secret_store.put("token", "two")

    assert secret_store.get("token") == "two"
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


def test_a_hub_restart_reads_the_secrets_back(tmp_path: Path) -> None:
    home = tmp_path / "home"
    first = SecretStore(home)
    first.put("linear-token", SECRET)
    first.close()

    second = SecretStore(home)
    try:
        assert second.get("linear-token") == SECRET
    finally:
        second.close()


def test_a_value_stored_with_a_different_key_is_refused_by_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    store = SecretStore(home)
    store.put("token", SECRET)
    store.close()
    # Simulate "the database was copied without its key".
    (home / SECRETS_KEY_NAME).unlink()

    reopened = SecretStore(home)
    try:
        with pytest.raises(SecretStoreError) as excinfo:
            reopened.get("token")
    finally:
        reopened.close()
    assert "token" in str(excinfo.value)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize("name", ["", " ", "has space", "a/b", "x" * 129, "-leading"])
def test_bad_secret_names_are_refused_loudly(name: str) -> None:
    with pytest.raises(SecretStoreError):
        validate_secret_name(name)


def test_an_empty_value_is_refused_rather_than_stored(secret_store: SecretStore) -> None:
    with pytest.raises(SecretStoreError):
        secret_store.put("token", "")


def test_nothing_logged_while_storing_or_reading_contains_the_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="palaia_hub")
    store = SecretStore(tmp_path / "home")
    try:
        store.put("linear-token", SECRET)
        assert store.get("linear-token") == SECRET
        store.delete("linear-token")
    finally:
        store.close()

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in logged
    # The name, on the other hand, is deliberately loggable.
    assert "linear-token" in logged
