"""Pydantic result shapes for the stash tool family (SPEC-202).

Mirrors :mod:`palaia_hub.gateway.vault_protocol`'s pattern: small, explicit
result models used both as a tool's ``structured_content`` and as the REST
mirror's JSON response body.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StashEntry(BaseModel):
    """One stash entry as returned to a caller."""

    namespace: str
    key: str
    value: Any
    created_at: float
    updated_at: float
    accessed_at: float
    expires_at: float | None
    stale_at: float | None
    stale: bool
    size_bytes: int


class SetResult(BaseModel):
    namespace: str
    key: str
    size_bytes: int
    evicted: list[str]


class GetResult(BaseModel):
    namespace: str
    key: str
    found: bool
    entry: StashEntry | None


class DelResult(BaseModel):
    namespace: str
    key: str
    deleted: bool


class ListResult(BaseModel):
    namespace: str
    entries: list[StashEntry]


class StatusResult(BaseModel):
    total_entries: int
    total_bytes: int
    budget_bytes: int
    namespaces: dict[str, int]


class StashError(Exception):
    """Raised by :class:`~palaia_hub.stash.store.StashStore` for a bad call
    (a value too large for the per-entry limit, an invalid key/namespace).
    Turned into a ``ToolResult(is_error=True, ...)`` by the gateway layer,
    never an uncaught exception (same convention as ``VaultServiceError``).
    """


__all__ = [
    "DelResult",
    "GetResult",
    "ListResult",
    "SetResult",
    "StashEntry",
    "StashError",
    "StatusResult",
]
