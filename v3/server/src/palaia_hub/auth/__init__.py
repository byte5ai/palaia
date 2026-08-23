"""palaia's MVP auth: named, argon2id-hashed per-client tokens (SPEC-108).

Public surface:

- :class:`~palaia_hub.auth.store.TokenStore` — create/list/revoke/verify
  named tokens, hashed at rest. Never holds a plaintext token after
  :meth:`~palaia_hub.auth.store.TokenStore.create` returns it.
- :class:`~palaia_hub.auth.verifier.PalaiaTokenVerifier` — adapts a
  ``TokenStore`` to fastmcp's ``TokenVerifier`` seam
  (``FastMCP(auth=...)``); see that module's docstring for the Phase-2
  OAuth upgrade path this exists to keep open.
- :func:`~palaia_hub.auth.wiring.build_profile_verifiers` — one verifier
  per gateway profile, for :func:`palaia_hub.gateway.build.build_gateway`'s
  ``token_verifiers`` parameter.
- :func:`~palaia_hub.auth.enforcement.missing_scope_error` — the per-tool
  read/write scope check :mod:`palaia_hub.gateway.memory_tools` calls.
- :mod:`palaia_hub.auth.scopes` — the ``vault:<key>:read|write`` scope
  vocabulary and which of the eight memory-tool actions need which.
- :func:`~palaia_hub.auth.policy.check_gateway_auth_policy` — the
  cloud/open "every mounted profile must have a verifier" guard
  :func:`palaia_hub.app.create_app` runs before mounting a gateway.
- :func:`~palaia_hub.auth.routes.build_auth_router` — the
  ``/api/auth/tokens`` REST surface.
"""

from __future__ import annotations

from .enforcement import missing_scope_error, missing_stash_scope_error
from .models import CreatedToken, TokenInfo, TokenRecord
from .policy import AuthPolicyError, check_gateway_auth_policy
from .routes import build_auth_router
from .scopes import (
    READ_ACTIONS,
    STASH_READ_ACTIONS,
    STASH_WRITE_ACTIONS,
    WRITE_ACTIONS,
    required_scope_for_action,
    required_scope_for_stash_action,
    stash_scope,
    vault_scope,
)
from .store import TokenError, TokenStore
from .verifier import PalaiaTokenVerifier
from .wiring import build_profile_verifiers

__all__ = [
    "READ_ACTIONS",
    "STASH_READ_ACTIONS",
    "STASH_WRITE_ACTIONS",
    "WRITE_ACTIONS",
    "AuthPolicyError",
    "CreatedToken",
    "PalaiaTokenVerifier",
    "TokenError",
    "TokenInfo",
    "TokenRecord",
    "TokenStore",
    "build_auth_router",
    "build_profile_verifiers",
    "check_gateway_auth_policy",
    "missing_scope_error",
    "missing_stash_scope_error",
    "required_scope_for_action",
    "required_scope_for_stash_action",
    "stash_scope",
    "vault_scope",
]
