"""Token data shapes: the stored record, and its hash-free public views."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TokenRecord(BaseModel):
    """One client token as persisted in the store — includes the hash.

    Never serialize this to a REST response or a CLI listing; use
    :class:`TokenInfo` for that (see :meth:`TokenInfo.from_record`). ``id``
    is a public, non-secret identifier (see ``store.py``'s module
    docstring) — only ``hash`` is sensitive, and it never leaves the store.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    profile: str
    scopes: list[str] = Field(default_factory=list)
    hash: str
    created_at: str
    revoked_at: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class TokenInfo(BaseModel):
    """The hash-free, safe-to-show view of a :class:`TokenRecord`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    profile: str
    scopes: list[str]
    created_at: str
    revoked_at: str | None = None

    @classmethod
    def from_record(cls, record: TokenRecord) -> TokenInfo:
        return cls(
            id=record.id,
            name=record.name,
            profile=record.profile,
            scopes=record.scopes,
            created_at=record.created_at,
            revoked_at=record.revoked_at,
        )


class CreatedToken(BaseModel):
    """A freshly created token: its info, plus the plaintext — shown once.

    Nothing else in this codebase ever holds the plaintext after this
    object is handed back to whoever called :meth:`TokenStore.create`; the
    store itself only ever wrote the hash.
    """

    model_config = ConfigDict(extra="forbid")

    info: TokenInfo
    token: str


__all__ = ["CreatedToken", "TokenInfo", "TokenRecord"]
