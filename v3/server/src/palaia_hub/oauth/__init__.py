"""palaia as an OAuth 2.1 authorization server *and* resource server (SPEC-203).

This is the Phase-2 identity core: with it enabled, claude.ai, ChatGPT and
mobile apps connect to a self-hosted palaia hub as ordinary remote
connectors, through the standard flow their vendor clouds already speak.

Shape (MASTERPLAN §5.5): **one authorization server fronting N resources.**
Each mounted MCP profile is a distinct protected resource with its own
canonical audience; access tokens are short-lived, audience-scoped JWTs, and
each profile verifies them locally against the published public key — no
per-call round trip back to this package. Nothing in the token path talks to
the vault.

Every production lesson from the mcp-hub prototype is implemented here as a
mechanism rather than a note, each in one place:

* **Grace-windowed refresh rotation** —
  :meth:`palaia_hub.oauth.store.OAuthStore.rotate_refresh_token`. Strict
  single-use caused daily re-logins when one connector fanned out over web,
  phone and desktop; a spent token stays usable for a configurable window so
  concurrent refreshes converge instead of tearing the grant down.
* **Resolved resource indicators** —
  :class:`palaia_hub.oauth.resources.ResourceRegistry`. The ``aud`` claim is
  always a string this hub composed; a client's RFC 8707 ``resource`` is
  matched against known profiles, never copied.
* **Registered-client garbage collection** —
  :meth:`palaia_hub.oauth.store.OAuthStore.prune_clients`. Self-registered
  clients that hold no live refresh token and have gone unused are pruned;
  admin-provisioned machine clients never are.
* **Explicit SQLite connection and locking discipline** —
  :mod:`palaia_hub.oauth.store`'s module docstring. One connection, one lock,
  ``BEGIN IMMEDIATE`` around every multi-statement mutation.

Public surface:

- :class:`~palaia_hub.oauth.service.AuthorizationServer` — every protocol
  decision (discovery, authorize, token, revoke, register, sign-in).
- :func:`~palaia_hub.oauth.routes.build_oauth_router` — its HTTP surface,
  mounted by :func:`palaia_hub.app.create_app`.
- :func:`~palaia_hub.oauth.verifier.build_profile_auth` — the resource side:
  per-profile fastmcp ``JWTVerifier`` (SPEC-108's upgrade seam), combined via
  ``MultiAuth`` with the SPEC-108 ``plt_`` verifier so both credentials keep
  working on every profile.
- :func:`~palaia_hub.oauth.clients.provision_machine_client` — the only way a
  confidential (secret-bearing, audience-pinned) client comes into existence.
- :func:`~palaia_hub.oauth.login.set_owner_password` — the local owner
  account behind ``/oauth/login``.
"""

from __future__ import annotations

from .cimd import CimdFetcher, StaticCimdFetcher
from .clients import provision_machine_client, register_dcr_client
from .errors import OAuthError
from .keys import ALGORITHM, SigningKey, now_seconds
from .login import LoginThrottle, set_owner_password
from .models import (
    ClientInfo,
    ClientRow,
    IssuedTokens,
    ProvisionedMachineClient,
    PruneReport,
    RotationOutcome,
)
from .resources import ResourceRegistry, normalize_issuer
from .routes import build_oauth_router
from .service import AuthorizationServer, AuthorizeRedirect, LoginRequired
from .store import OAuthStore
from .verifier import (
    build_jwt_verifier,
    build_profile_auth,
    log_profile_auth,
    summarize_profile_auth,
)

__all__ = [
    "ALGORITHM",
    "AuthorizationServer",
    "AuthorizeRedirect",
    "CimdFetcher",
    "ClientInfo",
    "ClientRow",
    "IssuedTokens",
    "LoginRequired",
    "LoginThrottle",
    "OAuthError",
    "OAuthStore",
    "ProvisionedMachineClient",
    "PruneReport",
    "ResourceRegistry",
    "RotationOutcome",
    "SigningKey",
    "StaticCimdFetcher",
    "build_jwt_verifier",
    "build_oauth_router",
    "build_profile_auth",
    "log_profile_auth",
    "normalize_issuer",
    "now_seconds",
    "provision_machine_client",
    "register_dcr_client",
    "set_owner_password",
    "summarize_profile_auth",
]
