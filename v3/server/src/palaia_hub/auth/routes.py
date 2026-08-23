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
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .models import CreatedToken, TokenInfo
from .store import TokenError, TokenStore


class CreateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    profile: str
    scopes: list[str] = Field(default_factory=list)


def build_auth_router(store: TokenStore) -> APIRouter:
    """Build the ``/api/auth/tokens`` router, backed by ``store``."""
    router = APIRouter(prefix="/api/auth/tokens", tags=["auth"])

    @router.post("", response_model=CreatedToken)
    async def create_token(body: CreateTokenRequest) -> CreatedToken:
        try:
            return store.create(body.name, body.profile, body.scopes)
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
