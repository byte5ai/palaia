"""Row shapes the OAuth store hands back, and the API views built from them.

The ``*Row`` dataclasses are frozen and carry *only* hashes, never plaintext
credentials — the plaintext exists exactly once, in the return value of the
call that minted it, on its way into an HTTP response body. Anything that
reaches a REST/CLI surface goes through the hash-free views at the bottom of
this module, the same split :mod:`palaia_hub.auth.models` makes between
``TokenRecord`` and ``TokenInfo``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: How a client came to exist. ``cimd`` — its ``client_id`` is an https URL
#: resolving to a Client ID Metadata Document (MCP 2026-07-28's recommended
#: registration); ``dcr`` — RFC 7591 dynamic registration, deprecated but
#: still what several shipping clients do; ``admin`` — provisioned by the
#: operator (machine identities live here and only here).
ClientSource = Literal["cimd", "dcr", "admin"]


@dataclass(frozen=True, slots=True)
class ClientRow:
    """A registered OAuth client."""

    client_id: str
    source: ClientSource
    client_name: str
    redirect_uris: tuple[str, ...]
    grant_types: tuple[str, ...]
    scopes: tuple[str, ...]
    created_at: int
    last_seen_at: int
    #: argon2id hash of the client secret, for confidential (machine)
    #: clients only. ``None`` for every public client — public clients
    #: authenticate with PKCE, not a secret.
    client_secret_hash: str | None = None
    #: Machine identities are pinned to exactly one audience at provisioning
    #: time (MASTERPLAN §5.5) and can never be issued a token for another.
    pinned_audience: str | None = None
    is_machine: bool = False

    @property
    def is_public(self) -> bool:
        return self.client_secret_hash is None


@dataclass(frozen=True, slots=True)
class GrantRow:
    """One user↦client authorization, the unit refresh tokens hang off.

    Revoking a grant kills every refresh token derived from it in one step
    (and, once their short TTL elapses, every access token too).
    """

    grant_id: str
    client_id: str
    subject: str
    audience: str
    scopes: tuple[str, ...]
    created_at: int
    revoked_at: int | None = None


@dataclass(frozen=True, slots=True)
class CodeRow:
    """An authorization code, stored only as a digest of itself."""

    code_hash: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    audience: str
    subject: str
    scopes: tuple[str, ...]
    created_at: int
    expires_at: int
    consumed_at: int | None = None


@dataclass(frozen=True, slots=True)
class RefreshRow:
    """A refresh token, stored only as a digest of itself.

    ``rotated_at``/``successor_hash``/``grace_until`` implement the
    grace-windowed rotation the SPEC requires — see
    :meth:`palaia_hub.oauth.store.OAuthStore.rotate_refresh_token`.
    """

    token_hash: str
    grant_id: str
    client_id: str
    created_at: int
    expires_at: int
    rotated_at: int | None = None
    successor_hash: str | None = None
    grace_until: int | None = None
    revoked_at: int | None = None


@dataclass(frozen=True, slots=True)
class RotationOutcome:
    """The result of one refresh-token exchange.

    ``replayed`` is ``True`` when the presented token had already been spent
    and was accepted inside its grace window — the multi-device fan-out case
    (see :meth:`palaia_hub.oauth.store.OAuthStore.rotate_refresh_token`).
    """

    grant: GrantRow
    refresh_token: str
    refresh_expires_at: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """What a successful ``/token`` call produced, on its way to the response.

    The only object in this package that holds plaintext credentials; it is
    constructed inside a service call and consumed by the route that
    serializes it. Nothing stores it.
    """

    access_token: str
    expires_in: int
    scopes: tuple[str, ...]
    audience: str
    refresh_token: str | None = None


@dataclass(frozen=True, slots=True)
class IdpStateRow:
    """One pending IdP sign-in ticket (SPEC-204).

    Everything the callback needs to resume the *outer* ``/oauth/authorize``
    continuation lives here, server-side, keyed by the opaque ``state`` the
    browser carries to and from the provider — the continuation itself never
    appears in a URL. Consuming it (see
    :meth:`palaia_hub.oauth.store.OAuthStore.consume_idp_state`) deletes the
    row, which is what makes the ticket single-use.

    ``nonce_hash`` is the hash of the cookie the browser that *started* the
    flow was given (issue #345): the callback must arrive with that cookie,
    so a ``state`` completed in one browser cannot sign in another.
    """

    provider: str
    next_url: str
    nonce_hash: str | None = None


@dataclass(frozen=True, slots=True)
class ProvisionedMachineClient:
    """An admin-provisioned machine client, plus its secret — shown once."""

    client: ClientRow
    client_secret: str


@dataclass(slots=True)
class PruneReport:
    """What one registered-client GC pass did."""

    ran: bool
    pruned: list[str] = field(default_factory=list)
    kept_machine: int = 0
    kept_active: int = 0

    @property
    def pruned_count(self) -> int:
        return len(self.pruned)


class ClientInfo(BaseModel):
    """The hash-free, safe-to-show view of a :class:`ClientRow`."""

    model_config = ConfigDict(extra="forbid")

    client_id: str
    source: str
    client_name: str
    redirect_uris: list[str]
    grant_types: list[str]
    scopes: list[str]
    created_at: int
    last_seen_at: int
    is_machine: bool
    pinned_audience: str | None = None

    @classmethod
    def from_row(cls, row: ClientRow) -> ClientInfo:
        return cls(
            client_id=row.client_id,
            source=row.source,
            client_name=row.client_name,
            redirect_uris=list(row.redirect_uris),
            grant_types=list(row.grant_types),
            scopes=list(row.scopes),
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            is_machine=row.is_machine,
            pinned_audience=row.pinned_audience,
        )


__all__ = [
    "ClientInfo",
    "ClientRow",
    "ClientSource",
    "CodeRow",
    "GrantRow",
    "IssuedTokens",
    "ProvisionedMachineClient",
    "PruneReport",
    "RefreshRow",
    "RotationOutcome",
]
