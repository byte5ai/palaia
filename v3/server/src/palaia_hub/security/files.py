"""The on-disk posture every hub store shares (SPEC-502 deliverable #2).

One rule, written once: **everything palaia persists is readable only by
the account that runs the hub** — ``0600`` for files, ``0700`` for the
directories that hold them. The hub's home sits inside a user's own home on
a laptop, inside a mounted volume in the container, and inside whatever a
NAS app store hands it; on every one of those a group- or world-readable
byte is a byte someone else on the box can read.

**Why this module exists rather than a ``chmod`` per store.** Before this
SPEC the rule was written down three times (the OAuth signing key, the OAuth
database, the upstream secret store) and *not* written down in the nine
other places that persist state — the stash, the session directory, the
messenger, notifications, both outboxes, the marketplace caches and the
per-vault index. A rule with nine exceptions is not a rule. Every store now
calls into this module, and
``server/tests/security/test_store_file_modes.py`` walks a real hub home
after exercising every store and fails on anything wider.

**SQLite write-ahead siblings.** Narrowing ``foo.db`` does nothing for
``foo.db-wal`` and ``foo.db-shm``, which SQLite creates itself with the
process umask (typically ``0644``) and which hold *the same pages* as the
database — a committed row lives in the WAL until the next checkpoint. The
audit that motivated this module found exactly that: databases at ``0600``
next to world-readable write-ahead files. :func:`harden_sqlite_database`
narrows the whole set, and stores call it after opening (the siblings appear
when the WAL journal mode is set) and again on close.

**Failures are logged, never raised.** Some container and network mounts
cannot represent POSIX modes at all; a hub must still start there, and the
operator must still see it in the log. That is the same trade
:func:`enforce_private_mode` has always made — this module is where it now
lives, with :mod:`palaia_hub.oauth.keys` re-exporting the name its callers
already import.
"""

from __future__ import annotations

import logging
import stat
from pathlib import Path

logger = logging.getLogger("palaia_hub.security.files")

#: Directories the hub creates for its own state.
DIR_MODE = 0o700
#: Files the hub creates for its own state.
FILE_MODE = 0o600

#: The files SQLite creates alongside a database. ``-wal``/``-shm`` are the
#: write-ahead pair; ``-journal`` is the rollback journal a non-WAL database
#: (or one mid-downgrade) uses instead. All three carry database content.
SQLITE_SIBLING_SUFFIXES: tuple[str, ...] = ("", "-wal", "-shm", "-journal")

#: SQLite's in-memory database name — several stores accept it in tests, and
#: it names no file to narrow.
MEMORY_DATABASE = ":memory:"


def enforce_private_mode(path: Path, mode: int) -> None:
    """Narrow ``path`` to ``mode`` if it is currently wider.

    Called on every load, not only at creation: a key or database whose
    permissions were widened (an ``rsync -a`` from a laxer box, a manual
    ``chmod``) is quietly narrowed again. Failures are logged rather than
    raised — a filesystem that cannot represent POSIX modes at all (some
    network and container mounts) must not stop the hub from starting, but
    the operator should see it in the log.
    """
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != mode:
            path.chmod(mode)
    except OSError as exc:  # pragma: no cover - platform dependent
        logger.warning("could not enforce mode %o on %s: %s", mode, path, exc)


def harden_file(path: Path) -> None:
    """Narrow one persisted file to :data:`FILE_MODE`, if it exists."""
    if path.exists():
        enforce_private_mode(path, FILE_MODE)


def harden_directory(path: Path) -> None:
    """Narrow one hub-owned directory to :data:`DIR_MODE`, if it exists."""
    if path.is_dir():
        enforce_private_mode(path, DIR_MODE)


def harden_sqlite_database(path: Path, *, with_parent: bool = False) -> None:
    """Narrow a SQLite database **and its write-ahead siblings**.

    Args:
        path: the database file itself. Siblings are derived by suffix
            (:data:`SQLITE_SIBLING_SUFFIXES`), and each is narrowed only if
            it exists — a freshly opened database has no ``-journal``, and a
            closed one has no ``-wal``.
        with_parent: also narrow the directory holding the database. Left
            off by default because several databases live in directories the
            *user* owns and arranges (a vault's ``.palaia/``), where the hub
            has no business re-modeling the tree; on by default for nothing,
            passed explicitly by the stores that create their own directory.

    A path of ``":memory:"`` (what several stores use in tests) is a no-op:
    there is no file to narrow.
    """
    if str(path) == MEMORY_DATABASE:
        return
    for suffix in SQLITE_SIBLING_SUFFIXES:
        sibling = path.with_name(path.name + suffix)
        if sibling.exists():
            enforce_private_mode(sibling, FILE_MODE)
    if with_parent:
        harden_directory(path.parent)


__all__ = [
    "DIR_MODE",
    "FILE_MODE",
    "MEMORY_DATABASE",
    "SQLITE_SIBLING_SUFFIXES",
    "enforce_private_mode",
    "harden_directory",
    "harden_file",
    "harden_sqlite_database",
]
