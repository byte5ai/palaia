"""Hook data shapes: the stored record, its secret-free view, and dead letters."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HookRecord(BaseModel):
    """One outbound webhook as persisted in ``hooks.yaml`` — includes the secret.

    Never serialize this to a REST response or a log line; use
    :class:`HookInfo` for that. ``secret`` is the live HMAC-SHA256 signing
    key for every delivery this hook receives — unlike a client token
    (:mod:`palaia_hub.auth`), it must stay retrievable server-side (there is
    no way to *verify* a signature without the key that produced it), so it
    is stored as plain text here rather than hashed. It is shown to the
    caller once, at creation, and never again.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    url: str
    #: Event-name filters this hook receives. ``["*"]`` means every event.
    events: list[str] = Field(default_factory=lambda: ["*"])
    secret: str
    enabled: bool = True
    created_at: str

    def matches(self, event_name: str) -> bool:
        if event_name in self.events:
            return True
        # "*" means every event that describes something that happened. The
        # hub's own 15-second `health` heartbeat is not one of those, and a
        # wildcard hook used to receive ~5,760 of them a day, each a durable
        # outbox row (issues #338/#339). Name it to get it.
        return "*" in self.events and event_name != "health"


class HookInfo(BaseModel):
    """The secret-free, safe-to-show view of a :class:`HookRecord`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    url: str
    events: list[str]
    enabled: bool
    created_at: str

    @classmethod
    def from_record(cls, record: HookRecord) -> HookInfo:
        return cls(
            id=record.id,
            url=record.url,
            events=record.events,
            enabled=record.enabled,
            created_at=record.created_at,
        )


class CreatedHook(BaseModel):
    """A freshly created hook: its info, plus the plaintext secret — shown once."""

    model_config = ConfigDict(extra="forbid")

    info: HookInfo
    secret: str


class DeadLetter(BaseModel):
    """One delivery that exhausted its retries — visible via REST (deliverable #2)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    hook_id: str
    event_id: str
    event_name: str
    attempts: int
    last_error: str
    created_at: str


__all__ = ["CreatedHook", "DeadLetter", "HookInfo", "HookRecord"]
