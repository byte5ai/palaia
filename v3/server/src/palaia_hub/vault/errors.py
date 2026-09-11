"""Exception hierarchy for the vault engine.

Every error carries a message a human can act on: what was attempted, on
which vault-relative path, and what to do instead.
"""

from __future__ import annotations

from collections.abc import Sequence


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


class UncommittedWriteError(GitError):
    """The change reached disk, but its git commit failed (issue #333).

    The files are exactly what the caller asked for and the engine's catalog
    already reflects them; only the commit is missing. The engine remembers
    the paths and commits them — with the original message and attribution —
    at the start of its next successful operation, or when the same write is
    retried. :attr:`events` are the change events the operation would have
    published; the engine publishes them anyway, so the index reflects disk.
    """

    def __init__(self, message: str, *, events: Sequence[object] = ()) -> None:
        super().__init__(message)
        self.events = tuple(events)


class MalformedFrontmatterError(VaultError):
    """The note's frontmatter fence is present but unparseable (issue #335).

    Re-rendering such a note from the empty parse would silently discard the
    user's original YAML block, so every write that rebuilds frontmatter is
    refused until the file is repaired outside the engine.
    """


class NoteEncodingError(VaultError):
    """The note's bytes are not valid UTF-8 (issue #355).

    The engine reads such a note with replacement characters so it can still
    be listed and searched, but refuses to *rewrite* it: writing the decoded
    text back would replace every undecodable byte with U+FFFD for good —
    a Latin-1 note would lose its umlauts on its first edit.
    """
