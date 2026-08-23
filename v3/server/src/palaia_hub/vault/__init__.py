"""The palaia vault engine — files are the only truth.

Public surface of SPEC-102:

* :class:`VaultEngine` — per-vault CRUD, identity rename, git history and the
  doctor hook points. Every mutating call is synchronous write-through:
  tmp + fsync + atomic rename, then one attributed git commit.
* :class:`VaultRegistry` — many vaults, physically isolated.
* :class:`VaultWatcher` — external change detection with checksum-based move
  detection (``watchfiles`` reports renames as delete+add).
* :class:`VaultDoctor` — ``verify()`` findings, safe repairs, ``reindex()``.
* :mod:`.events` — the typed change-event vocabulary and the Phase-1 bus stub.

Note *semantics* (observations, relations, embeds, the warning taxonomy) are
SPEC-103's; this package handles files, identity, watching, git and locking.
"""

from __future__ import annotations

from .atomic import atomic_write_bytes, atomic_write_text, sha256_bytes, sha256_file
from .doctor import Finding, IndexEntry, IndexView, ReindexSink, VaultDoctor, summarize
from .engine import CatalogEntry, VaultEngine
from .errors import (
    AmbiguousReferenceError,
    ChecksumConflictError,
    GitError,
    InvalidPathError,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    VaultConfigError,
    VaultError,
    VaultFormatVersionError,
    VaultNotFoundError,
    VolatileNameError,
)
from .events import (
    ChangeEvent,
    EntityRenamed,
    EventBus,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
    VaultEvent,
)
from .gitlayer import DEFAULT_POLICY, GitPolicy, GitRepo, LockRecovery
from .models import (
    ENGINE,
    HUMAN,
    MANIFEST_PATH,
    VAULT_FORMAT_VERSION,
    Attribution,
    CommitInfo,
    DirEntry,
    Note,
    RenameResult,
    VaultInfo,
    WriteResult,
)
from .registry import VaultRecord, VaultRegistry
from .watcher import DEFAULT_DEBOUNCE_MS, VaultWatcher, WatcherStats

__all__ = [
    "DEFAULT_DEBOUNCE_MS",
    "DEFAULT_POLICY",
    "ENGINE",
    "HUMAN",
    "MANIFEST_PATH",
    "VAULT_FORMAT_VERSION",
    "AmbiguousReferenceError",
    "Attribution",
    "CatalogEntry",
    "ChangeEvent",
    "ChecksumConflictError",
    "CommitInfo",
    "DirEntry",
    "EntityRenamed",
    "EventBus",
    "Finding",
    "GitError",
    "GitPolicy",
    "GitRepo",
    "IndexEntry",
    "IndexView",
    "InvalidPathError",
    "LockRecovery",
    "Note",
    "NoteCreated",
    "NoteDeleted",
    "NoteExistsError",
    "NoteModified",
    "NoteMoved",
    "NoteNotFoundError",
    "PermalinkConflictError",
    "ReindexSink",
    "RenameResult",
    "VaultConfigError",
    "VaultDoctor",
    "VaultEngine",
    "VaultError",
    "VaultEvent",
    "VaultFormatVersionError",
    "VaultInfo",
    "VaultNotFoundError",
    "VaultRecord",
    "VaultRegistry",
    "VaultWatcher",
    "VolatileNameError",
    "WatcherStats",
    "WriteResult",
    "atomic_write_bytes",
    "atomic_write_text",
    "sha256_bytes",
    "sha256_file",
    "summarize",
]
