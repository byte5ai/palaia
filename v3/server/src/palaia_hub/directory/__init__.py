"""The session directory: sessions become visible (SPEC-402, MASTERPLAN's
first half of §5.4).

Deliberately separate from the vault (knowledge), the index (search), and
the stash (cache): a session row is presence/liveness metadata — who is
connected, doing what, since when — never content of any kind. The
messenger (SPEC-403) addresses into this directory rather than reinventing
discovery.

Public surface:

- :class:`~palaia_hub.directory.store.DirectoryStore` — the SQLite engine:
  handle + hashed session secret, TTL/stale/prune lifecycle, filterable
  list/query.
- :class:`~palaia_hub.directory.service.DirectoryService` — the async
  facade the gateway tools and the REST mirror both call.
- :mod:`palaia_hub.directory.models` — the result shapes shared by both.
"""

from __future__ import annotations

from .models import (
    DeregisterResult,
    DirectoryError,
    HeartbeatResult,
    ListResult,
    QueryResult,
    RegisterResult,
    ReportedStatus,
    SessionNotFoundError,
    SessionRecord,
    SessionSecretMismatchError,
    SessionStatus,
    UpdateResult,
)
from .service import DirectoryService, Publisher
from .store import DEFAULT_TTL_SECONDS, PRUNE_TTL_MULTIPLIER, DirectoryStore

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "PRUNE_TTL_MULTIPLIER",
    "DeregisterResult",
    "DirectoryError",
    "DirectoryService",
    "DirectoryStore",
    "HeartbeatResult",
    "ListResult",
    "Publisher",
    "QueryResult",
    "RegisterResult",
    "ReportedStatus",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionSecretMismatchError",
    "SessionStatus",
    "UpdateResult",
]
