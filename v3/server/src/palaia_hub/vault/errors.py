"""Exception hierarchy for the vault engine.

Every error carries a message a human can act on: what was attempted, on
which vault-relative path, and what to do instead.
"""

from __future__ import annotations


class VaultError(RuntimeError):
    """Base class for every vault-engine failure."""


class VaultNotFoundError(VaultError):
    """The vault directory or registry entry does not exist."""


class VaultConfigError(VaultError):
    """A vault registry entry is invalid (bad name, duplicate, nested path)."""


class VaultFormatVersionError(VaultError):
    """The vault manifest declares a ``vault_format`` this engine cannot write.

    Reads degrade to best-effort (format spec §1.1); writes are refused.
    """


class NoteNotFoundError(VaultError):
    """No note matched the given reference."""


class NoteExistsError(VaultError):
    """A note already exists at the target path and creation was requested."""


class InvalidPathError(VaultError):
    """A path escapes the vault root or names engine-private storage."""


class ChecksumConflictError(VaultError):
    """The note changed on disk since the caller last read it.

    Optimistic concurrency: the caller passed ``expected_checksum`` and the
    file's current checksum differs, so the write was refused rather than
    silently clobbering the other writer's content.
    """


class AmbiguousReferenceError(VaultError):
    """A reference matched more than one note; the candidates are listed."""


class PermalinkConflictError(VaultError):
    """The requested permalink is already taken by another note."""


class VolatileNameError(VaultError):
    """A title or permalink carries volatile data (version, date, vX.Y).

    Format spec §4.1: the *writer* rejects volatile names; the parser only
    warns, so existing user files are never rejected.
    """


class GitError(VaultError):
    """A git operation on the vault repository failed."""
