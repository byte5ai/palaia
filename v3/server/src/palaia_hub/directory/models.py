"""Pydantic result shapes for the session directory (SPEC-402).

Mirrors :mod:`palaia_hub.stash.models`'s pattern: small, explicit result
models used both as a tool's ``structured_content`` and as the REST
mirror's JSON response body. None of these ever carries a session secret —
that value is returned exactly once, from :class:`RegisterResult`, and
never again (not from ``list``, not from ``query``, not from a later
``heartbeat``/``update``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

#: Self-reported by a session (``directory_update``'s ``status`` field).
#: ``stale`` is never accepted as an input — see
#: :mod:`palaia_hub.directory.store`'s module docstring for why it is
#: always computed server-side from ``last_seen_at``/``ttl_seconds``.
ReportedStatus = Literal["active", "idle"]

#: The full status vocabulary a caller ever sees on a session row —
#: ``ReportedStatus`` plus the server-computed ``stale``.
SessionStatus = Literal["active", "idle", "stale"]


class SessionRecord(BaseModel):
    """One session, as returned to any caller (register/heartbeat/update/
    list/query). Never carries the session secret."""

    handle: str
    scope: str
    host: str
    platform: str
    agent_kind: str
    model: str
    status: SessionStatus
    capabilities: list[str]
    registered_at: float
    last_seen_at: float
    ttl_seconds: float


class RegisterResult(BaseModel):
    """``directory_register``'s result. ``session_secret`` is shown exactly
    once, here — the caller must hold onto it for every subsequent
    ``directory_heartbeat``/``directory_update``/``directory_deregister``
    call on this handle."""

    session: SessionRecord
    session_secret: str


class HeartbeatResult(BaseModel):
    session: SessionRecord


class UpdateResult(BaseModel):
    session: SessionRecord


class ListResult(BaseModel):
    sessions: list[SessionRecord]


class QueryResult(BaseModel):
    sessions: list[SessionRecord]


class DeregisterResult(BaseModel):
    handle: str
    deregistered: bool


class DirectoryError(Exception):
    """Raised by :class:`~palaia_hub.directory.store.DirectoryStore` for a
    bad call (unknown handle, wrong session secret). Turned into a
    ``ToolResult(is_error=True, ...)`` by the gateway layer, never an
    uncaught exception (same convention as ``StashError``)."""


class SessionNotFoundError(DirectoryError):
    """No session is registered under the given handle (or it already aged
    out past its prune threshold)."""


class SessionSecretMismatchError(DirectoryError):
    """The presented session secret does not match the one issued at
    registration for this handle — the impersonation guard (SPEC-402
    acceptance criterion: 'a wrong session secret cannot heartbeat/update/
    deregister another session')."""


__all__ = [
    "DeregisterResult",
    "DirectoryError",
    "HeartbeatResult",
    "ListResult",
    "QueryResult",
    "RegisterResult",
    "ReportedStatus",
    "SessionNotFoundError",
    "SessionRecord",
    "SessionSecretMismatchError",
    "SessionStatus",
    "UpdateResult",
]
