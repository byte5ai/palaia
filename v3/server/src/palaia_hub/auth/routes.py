"""REST surface for token management (SPEC-108 deliverable #1).

Mounted at ``/api/auth/tokens`` by :func:`palaia_hub.app.create_app` when it
is given a ``token_store`` (see that function's docstring for why the
parameter is opt-in). Like ``/api/health``/``/api/info`` today, these
routes carry no auth of their own — the admin/dashboard surface as a whole
is protected by network topology (the operating mode's VPN/tailnet-only
posture), not by a per-request credential check; SPEC-108's token/profile
auth is for MCP *clients*, not the dashboard. A dashboard login is
tracked separately (MASTERPLAN §5.5's "local account" / IdP sign-in,
Phase 2) and out of this SPEC's scope.

**SPEC-504 first-run funnel audit fix**: before this SPEC, an empty
``scopes`` list (what every dashboard caller — ``ConnectPanel.tsx``'s
"Issue token", which the onboarding wizard's own step 4 is a thin wrapper
around — has only ever sent; there is no scope picker in the UI) meant a
token that authenticates but then fails ``missing_scope_error``'s
per-action check on literally every memory-tool call, on any hub whose
mounted profile actually enforces scopes (``auth_enabled: true``, the
default in every mode, not only cloud/open). That made the wizard's own
target shape — "connect first client -> write first memory from the
client" — impossible to complete on a hub with auth on, which is the
common case. Fixed here, not by adding a scope picker (real, but a bigger
UI change than this instrumentation SPEC): an empty ``scopes`` list now
means "grant read+write on every vault the named profile mounts, right
now" — the same trust an unscoped ``plt_`` token already implied everywhere
*else* auth is optional (see :func:`palaia_hub.auth.enforcement.
missing_scope_error`'s own docstring on the locked-mode-with-no-verifier
case) — rather than silently meaning "nothing". An explicit, non-empty
``scopes`` list (a future scope picker's real use case) is still honored
exactly as given.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import CreatedToken, TokenInfo
from .scopes import directory_scope, messenger_scope, stash_scope, vault_scope
from .store import TokenError, TokenStore

if TYPE_CHECKING:
    # Deferred: only needed for the type hint below, and importing it at
    # module load time would reach back into `palaia_hub.gateway`, which
    # itself imports from this package (`palaia_hub.auth.policy`) — safe in
    # practice (that submodule is already fully loaded by the time either
    # side needs it) but fragile to depend on import order for. `TYPE_
    # CHECKING` sidesteps the question entirely: this name never actually
    # executes at runtime.
    from ..gateway.dynamic import DynamicGateway


class CreateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    profile: str
    scopes: list[str] = Field(default_factory=list)


def _default_scopes_for_profile(dynamic_gateway: DynamicGateway, profile: str) -> list[str]:
    """Read+write on every vault ``profile`` mounts right now, or ``[]``
    when the profile does not exist yet (a token can be pre-provisioned for
    a profile the wizard has not created — that stays today's "no scopes
    yet" behavior, not this default)."""
    for candidate in dynamic_gateway.config.profiles:
        if candidate.path == profile:
            scopes = [
                vault_scope(key, permission)
                for key in candidate.vaults
                for permission in ("read", "write")
            ]
            # Issue #313: the hub-wide mounts now require a token, so a
            # default token for a profile that carries a built-in family
            # (`stash`/`directory`/`messenger: true`) also gets that family's
            # scope pair — the same rule the OAuth server's grantable
            # ceiling already applies (`palaia_hub.cli._profile_scopes`).
            if candidate.stash:
                scopes += [stash_scope("read"), stash_scope("write")]
            if candidate.directory:
                scopes += [directory_scope("read"), directory_scope("write")]
            if candidate.messenger:
                scopes += [messenger_scope("read"), messenger_scope("send")]
            return scopes
    return []


def build_auth_router(
    store: TokenStore, *, dynamic_gateway: DynamicGateway | None = None
) -> APIRouter:
    """Build the ``/api/auth/tokens`` router, backed by ``store``.

    Args:
        store: as before this SPEC.
        dynamic_gateway: given, an empty ``scopes`` list in a create-token
            request is defaulted to read+write on every vault the named
            profile currently mounts (see the module docstring's SPEC-504
            note). Omitted, behavior is unchanged from before this SPEC — an
            empty list is created exactly as sent.
    """
    router = APIRouter(prefix="/api/auth/tokens", tags=["auth"])

    @router.post("", response_model=CreatedToken)
    async def create_token(body: CreateTokenRequest) -> CreatedToken:
        scopes = body.scopes
        if not scopes and dynamic_gateway is not None:
            scopes = _default_scopes_for_profile(dynamic_gateway, body.profile)
        try:
            return store.create(body.name, body.profile, scopes)
        except TokenError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("", response_model=list[TokenInfo])
    async def list_tokens() -> list[TokenInfo]:
        return store.list_tokens()

    @router.delete("/{token_id}", response_model=TokenInfo)
    async def revoke_token(token_id: str) -> TokenInfo:
        try:
            return store.revoke(token_id)
        except TokenError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


__all__ = ["build_auth_router"]
