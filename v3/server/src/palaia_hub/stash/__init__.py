"""Stash: the hub-level cross-session cache (SPEC-202, MASTERPLAN's P5 pillar).

Deliberately separate from the vault (knowledge) and the disposable index
(search): the three-stores lesson is "cache is not operating memory is not
knowledge" — a stash entry is a scratch value with a lifecycle (TTL, LRU
eviction), never a note. See :mod:`palaia_hub.gateway.stash_tools` for the
IDENTITY line every stash tool description carries to keep that boundary
visible to a calling model.

Public surface:

- :class:`~palaia_hub.stash.store.StashStore` — the SQLite engine: TTL +
  stale marker, per-entry size limit, total budget with LRU eviction.
- :class:`~palaia_hub.stash.service.StashService` — the async facade the
  gateway tools and the REST mirror both call.
- :mod:`palaia_hub.stash.models` — the result shapes shared by both.
"""

from __future__ import annotations

from .models import (
    DelResult,
    GetResult,
    ListResult,
    SetResult,
    StashEntry,
    StashError,
    StatusResult,
)
from .service import Publisher, StashService
from .store import DEFAULT_ENTRY_LIMIT_BYTES, DEFAULT_TOTAL_BUDGET_BYTES, StashStore

__all__ = [
    "DEFAULT_ENTRY_LIMIT_BYTES",
    "DEFAULT_TOTAL_BUDGET_BYTES",
    "DelResult",
    "GetResult",
    "ListResult",
    "Publisher",
    "SetResult",
    "StashEntry",
    "StashError",
    "StashService",
    "StashStore",
    "StatusResult",
]
