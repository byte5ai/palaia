"""The encrypted secret store (SPEC-302 deliverable #2 — fixed design).

Upstream API keys, bearer tokens and OAuth client secrets live here, and
nowhere else: not in ``config.yaml`` (which is plain text, edited by hand and
often copied around), not in a client's own configuration file, and never in
a log line or a REST response.

**On-disk shape** (fixed by the SPEC, implemented verbatim):

- ``<home>/secrets.sqlite3`` — one table, ``secrets(name, ciphertext,
  created_at, updated_at)``. Created ``0600`` inside the ``0700`` hub home.
- ``<home>/secrets.key`` — a single Fernet key (``cryptography``, already a
  dependency), created ``0600`` with ``O_CREAT | O_EXCL`` so the material is
  never briefly world-readable between ``open`` and ``chmod``, and never
  overwrites an existing key.

Both are re-narrowed on every load via
:func:`palaia_hub.security.files.enforce_private_mode` — the pattern
SPEC-203's signing key established, which SPEC-502 moved into
:mod:`palaia_hub.security.files` so every store in the hub shares one copy
of it. The database's write-ahead siblings are narrowed with it (SPEC-502
finding: they were not, and they carry the same pages).

**The never-return-values rule.** :meth:`SecretStore.get` exists because the
hub itself must decrypt a value to build an upstream's ``Authorization``
header or a child process's environment. That is the *only* consumer. No
REST response model in this repository has a field a secret value could be
placed in (see :mod:`palaia_hub.upstream.api` — the listing model carries
``name``/``created_at``/``updated_at`` and nothing else), and nothing in this
module logs a value, an exception message containing one, or a ciphertext.
Errors name the *secret's name* only. A test asserts all three halves of
that (``tests/upstream/test_secrets.py``,
``tests/upstream/test_secret_never_leaks.py``).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ..security.files import (
    DIR_MODE,
    FILE_MODE,
    enforce_private_mode,
    harden_directory,
    harden_sqlite_database,
)

logger = logging.getLogger("palaia_hub.upstream.secrets")

#: The encrypted store, in the hub home.
SECRETS_DB_NAME = "secrets.sqlite3"
#: The Fernet key that store is encrypted under, in the same home.
SECRETS_KEY_NAME = "secrets.key"

#: Secret names are operator-chosen identifiers that travel through URLs
#: (``PUT /api/secrets/{name}``) and into ``config.yaml`` as plain
#: references. Narrow, boring charset — a bad name is a loud error, never
#: silently sanitized (the same posture ``gateway/config.py`` takes for
#: vault keys and profile paths).
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class SecretStoreError(RuntimeError):
    """A secret could not be stored or read back.

    Its message names the secret by *name* and says what went wrong — never
    the value, never the ciphertext.
    """


def validate_secret_name(name: str) -> str:
    """Return ``name`` if it is a legal secret name, else raise.

    Raises:
        SecretStoreError: the name is empty, too long, or uses characters
            outside ``[A-Za-z0-9._-]``.
    """
    if not _NAME_RE.match(name):
        raise SecretStoreError(
            f"{name!r} is not a usable secret name. Use 1-128 characters from "
            "letters, digits, '.', '_' or '-', starting with a letter or digit."
        )
    return name


@dataclass(frozen=True, slots=True)
class SecretInfo:
    """What a listing may reveal about a stored secret: never its value."""

    name: str
    created_at: float
    updated_at: float


def load_or_create_key(home: Path) -> bytes:
    """Load ``<home>/secrets.key``, generating it if absent.

    The home directory is created ``0700`` if missing and re-narrowed if it
    was widened; the key file is created with ``O_CREAT | O_EXCL`` and an
    explicit ``0600`` mode, then re-narrowed on every load.
    """
    directory = Path(home)
    directory.mkdir(parents=True, exist_ok=True)
    enforce_private_mode(directory, DIR_MODE)
    path = directory / SECRETS_KEY_NAME
    if path.exists():
        enforce_private_mode(path, FILE_MODE)
        material = path.read_bytes().strip()
        try:
            Fernet(material)
        except (ValueError, TypeError) as exc:
            raise SecretStoreError(
                f"{path} does not contain a usable encryption key. Fix: move the "
                "file aside and re-enter your upstream secrets — palaia will "
                "generate a new key. (Every stored secret becomes unreadable, "
                "which is why the file is never overwritten automatically.)"
            ) from exc
        return material
    material = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        os.write(fd, material)
    finally:
        os.close(fd)
    enforce_private_mode(path, FILE_MODE)
    logger.info("generated a new secret-store encryption key at %s", path)
    return material


class SecretStore:
    """Write-mostly encrypted key/value store for upstream credentials.

    Args:
        home: the hub home. ``<home>/secrets.sqlite3`` and
            ``<home>/secrets.key`` are created there, both ``0600``.

    The API is deliberately tiny and matches the SPEC exactly:
    :meth:`put`, :meth:`get`, :meth:`delete`, :meth:`names`.
    """

    def __init__(self, home: Path) -> None:
        self._home = Path(home)
        self._key = load_or_create_key(self._home)
        self._fernet = Fernet(self._key)
        self._path = self._home / SECRETS_DB_NAME
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                name        TEXT PRIMARY KEY,
                ciphertext  BLOB NOT NULL,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            )
            """
        )
        self._conn.commit()
        # SPEC-502 finding: the paragraph that used to stand here claimed
        # SQLite creates the ``-wal``/``-shm`` siblings with the database's
        # own mode. It does not — it creates them under the process umask,
        # so this store's ciphertext pages sat in a world-readable
        # ``secrets.sqlite3-wal`` next to a ``0600`` database until the next
        # checkpoint. :func:`~palaia_hub.security.files.
        # harden_sqlite_database` narrows the whole set, here and on close.
        self._harden()

    # ------------------------------------------------------------------ API

    def put(self, name: str, value: str) -> SecretInfo:
        """Store (or replace) the secret called ``name``.

        Returns the metadata a caller may safely echo back — never the
        value it just wrote.
        """
        validate_secret_name(name)
        if not value:
            raise SecretStoreError(
                f"secret {name!r} would be empty. Fix: send the actual value, or "
                "delete the secret instead of blanking it."
            )
        now = time.time()
        ciphertext = self._fernet.encrypt(value.encode("utf-8"))
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO secrets (name, ciphertext, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    updated_at = excluded.updated_at
                """,
                (name, ciphertext, now, now),
            )
        logger.info("stored secret %r (%d bytes of ciphertext)", name, len(ciphertext))
        info = self.info(name)
        assert info is not None  # just written
        return info

    def get(self, name: str) -> str | None:
        """Decrypt and return the secret called ``name``, or ``None``.

        **In-process callers only** — see this module's docstring. The only
        consumers in this repository are
        :mod:`palaia_hub.upstream.service` (building an upstream's auth
        header or a child process's environment).
        """
        row = self._conn.execute(
            "SELECT ciphertext FROM secrets WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        try:
            return self._fernet.decrypt(row[0]).decode("utf-8")
        except InvalidToken as exc:
            raise SecretStoreError(
                f"secret {name!r} cannot be decrypted with the current "
                f"{SECRETS_KEY_NAME}. Fix: re-enter it (the key changed, or the "
                "database was copied without its key)."
            ) from exc

    def delete(self, name: str) -> bool:
        """Remove the secret called ``name``. ``True`` if it existed."""
        with self._conn:
            cursor = self._conn.execute("DELETE FROM secrets WHERE name = ?", (name,))
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("deleted secret %r", name)
        return deleted

    def names(self) -> list[SecretInfo]:
        """Every stored secret's name and timestamps, sorted by name."""
        rows = self._conn.execute(
            "SELECT name, created_at, updated_at FROM secrets ORDER BY name"
        ).fetchall()
        return [SecretInfo(name=r[0], created_at=r[1], updated_at=r[2]) for r in rows]

    def info(self, name: str) -> SecretInfo | None:
        """One secret's metadata, or ``None`` — never its value."""
        row = self._conn.execute(
            "SELECT name, created_at, updated_at FROM secrets WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return SecretInfo(name=row[0], created_at=row[1], updated_at=row[2])

    def has(self, name: str) -> bool:
        """Whether a secret called ``name`` exists."""
        return self.info(name) is not None

    def _harden(self) -> None:
        """Re-narrow the database, its write-ahead siblings and the home."""
        harden_sqlite_database(self._path)
        harden_directory(self._home)

    def close(self) -> None:
        """Close the SQLite handle."""
        self._conn.close()
        # Closing checkpoints and removes the ``-wal``/``-shm`` pair; a
        # rollback ``-journal`` can appear in its place on some platforms,
        # so the whole set is narrowed again here rather than assumed gone.
        self._harden()


__all__ = [
    "SECRETS_DB_NAME",
    "SECRETS_KEY_NAME",
    "SecretInfo",
    "SecretStore",
    "SecretStoreError",
    "load_or_create_key",
    "validate_secret_name",
]
