"""Adapts :class:`~palaia_hub.auth.store.TokenStore` to fastmcp's own auth seam.

``fastmcp.server.auth.TokenVerifier`` is fastmcp's abstract base for "check
a bearer token, hand back an ``AccessToken`` or ``None``" — the same base
class its own ``JWTVerifier`` (OAuth/OIDC-issued JWTs) implements. Handing a
``TokenVerifier`` instance to ``FastMCP(auth=...)`` is what makes fastmcp's
own ``RequireAuthMiddleware``/``BearerAuthBackend`` enforce it: every
request to that profile's MCP endpoint needs a bearer token this verifier
accepts, and a missing/invalid one gets fastmcp's own RFC 6750-compliant
401 + ``WWW-Authenticate`` — none of that is reimplemented here.

**This is the upgrade seam the SPEC asks for.** A Phase-2 OAuth
authorization server hands its issued JWTs to fastmcp's existing
``JWTVerifier`` instead of a :class:`PalaiaTokenVerifier` — a different
``TokenVerifier`` subclass on the same ``FastMCP(auth=...)`` parameter.
Nothing downstream cares which one produced the ``AccessToken``:
:mod:`palaia_hub.gateway.build` mounts whatever verifier it is given, and
:mod:`palaia_hub.auth.enforcement` (the per-tool scope check) reads only
``AccessToken.scopes``/``.client_id`` off whatever came back. Swapping the
verifier is the entire migration.

Deliberately NOT ``fastmcp.server.auth.StaticTokenVerifier``: that class
keeps its tokens in a plaintext ``dict`` and says so in its own docstring
("Never use this in production — tokens are stored in plain text!"). SPEC-
108 requires argon2id-hashed storage, which is exactly what
:class:`TokenStore` (and nothing else in this codebase) does.
"""

from __future__ import annotations

from fastmcp.server.auth import AccessToken, TokenVerifier

from .store import TokenStore


class PalaiaTokenVerifier(TokenVerifier):
    """Verifies a bearer token against ``store``, scoped to one MCP profile.

    Profile binding (SPEC-108 deliverable #2 — "a valid token bound to
    profile A cannot list/call profile B's tools") is enforced right here:
    one instance of this class is built per mounted profile (see
    :func:`palaia_hub.auth.wiring.build_profile_verifiers`), and a token
    whose record names a different profile fails verification exactly like
    an unknown or revoked one — indistinguishable to the client, all of
    them collapsing to fastmcp's standard 401.
    """

    def __init__(self, store: TokenStore, profile: str) -> None:
        super().__init__()
        self._store = store
        self._profile = profile

    async def verify_token(self, token: str) -> AccessToken | None:
        record = self._store.verify(token)
        if record is None or record.profile != self._profile:
            return None
        return AccessToken(
            token=token,
            client_id=record.id,
            scopes=list(record.scopes),
            subject=record.name,
        )


class HubTokenVerifier(TokenVerifier):
    """Verifies a bearer token against ``store`` for the hub-wide mounts.

    The six hub-level MCP surfaces (``/mcp/stash``, ``/mcp/directory``,
    ``/mcp/messenger``, ``/mcp/hub``, ``/mcp/market``, ``/mcp/team`` — see
    :func:`palaia_hub.app.create_app`) are not profiles: every client of this
    hub shares them. So the credential check here is "a live ``plt_`` token
    for *any* profile on this hub", and what the token may then do is decided
    by its hub-level scopes (``stash:*``/``directory:*``/``messenger:*``,
    :mod:`palaia_hub.auth.scopes`) inside each tool, exactly as on a profile.
    A revoked, expired or unknown token collapses to fastmcp's standard 401,
    same as :class:`PalaiaTokenVerifier` (issue #313).
    """

    def __init__(self, store: TokenStore) -> None:
        super().__init__()
        self._store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        record = self._store.verify(token)
        if record is None:
            return None
        return AccessToken(
            token=token,
            client_id=record.id,
            scopes=list(record.scopes),
            subject=record.name,
        )


__all__ = ["HubTokenVerifier", "PalaiaTokenVerifier"]
