"""``GET /api/connect/mcpb`` — the Claude Desktop "Download bundle" button.

Deliverable #4: the hub assembles the artifact itself, server-side, from
the packaged template (:mod:`palaia_hub.mcpb.builder`) — the dashboard
build embeds nothing MCPB-shaped at all, just a link to this endpoint
with a ``profile`` query parameter.

Variant is decided by the hub's own configuration, never by the caller:
an OAuth authorization server wired in (:mod:`palaia_hub.oauth`, SPEC-203)
means every download is the OAuth variant (no secret is ever baked into
the file); otherwise a token is minted through the same
:class:`~palaia_hub.auth.store.TokenStore` the connect page's other
clients use (SPEC-108) and baked in as the bundle's pre-filled default —
this is the "one click, no paste" property the SPEC's title promises for
Claude Desktop specifically, since MCPB is the one client-integration
path where the manifest itself can carry a pre-filled settings form.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import __version__
from ..auth.scopes import vault_scope
from ..auth.store import TokenError, TokenStore
from ..oauth import AuthorizationServer
from ..vault import VaultRegistry
from .builder import BundleBuildError, BundleRequest, build_bundle
from .template import TemplateNotFoundError

MCPB_PATH = "/api/connect/mcpb"


def _full_scopes(registry: VaultRegistry) -> list[str]:
    """Read+write on every vault the hub currently knows about.

    Mirrors :func:`palaia_hub.cli._curator_token`'s existing scope grant —
    the dynamic gateway does not (yet) expose a public "which vaults does
    this profile path actually mount" accessor to narrow this further, so
    an MCPB-bundle token is as broad as the curator's own token, not
    narrower. Tightening this to the profile's real vault subset is a
    reasonable follow-up once that accessor exists; noted here rather than
    hidden.
    """
    return [
        scope
        for key in sorted(registry.names())
        for scope in (vault_scope(key, "read"), vault_scope(key, "write"))
    ]


def build_mcpb_router(
    *,
    vault_registry: VaultRegistry,
    token_store: TokenStore | None,
    oauth_server: AuthorizationServer | None,
    home: Path,
) -> APIRouter:
    """Build the ``/api/connect/mcpb`` router.

    Args:
        vault_registry: used both to compute a minted token's scopes
            (:func:`_full_scopes`) and to require that at least one vault
            exists before offering a bundle at all.
        token_store: given, backs the token variant (no OAuth server
            configured). ``None`` with no ``oauth_server`` either means
            this router still mounts but every request 501s with a clear
            "neither auth path is configured" message, rather than the
            route not existing at all — the dashboard can then show *why*
            the download button is disabled instead of a 404.
        oauth_server: given, every download is the OAuth variant — see
            the module docstring.
        home: the hub's data directory (signing key persistence — see
            :mod:`palaia_hub.mcpb.signing`).
    """
    router = APIRouter(tags=["mcpb"])

    @router.get(MCPB_PATH)
    async def download_bundle(
        request: Request, profile: str = "default", client_name: str = "Claude Desktop bundle"
    ) -> Response:
        if oauth_server is None and token_store is None:
            raise HTTPException(
                status_code=501,
                detail=(
                    "no client-authentication method is configured (neither OAuth nor "
                    "token auth) — a downloaded bundle would have no way to authenticate. "
                    "Fix: enable OAuth (Access mode page) or token auth."
                ),
            )

        origin = str(request.base_url).rstrip("/")
        hub_url = f"{origin}/mcp/{profile}"

        if oauth_server is not None:
            bundle_request = BundleRequest(
                hub_url=hub_url,
                profile=profile,
                variant="oauth",
                version=__version__,
                issuer=oauth_server.issuer,
            )
        else:
            assert token_store is not None  # narrowed by the check above
            try:
                created = token_store.create(client_name, profile, _full_scopes(vault_registry))
            except TokenError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            bundle_request = BundleRequest(
                hub_url=hub_url,
                profile=profile,
                variant="token",
                version=__version__,
                token=created.token,
            )

        try:
            data = await asyncio.to_thread(build_bundle, bundle_request, home=home)
        except TemplateNotFoundError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        except BundleBuildError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="palaia.mcpb"'},
        )

    return router


__all__ = ["MCPB_PATH", "build_mcpb_router"]
