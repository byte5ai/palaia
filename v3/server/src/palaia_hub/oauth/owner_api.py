"""``/api/auth/owner`` — the first-run wizard's owner-account step (issue #342).

The install docs promised "an administrator sign-in for the dashboard" as
the wizard's first step; in reality the owner account could only be created
from a terminal (``palaia-hub oauth set-password``), and the login page told
a browser-only user — the Synology guide's whole audience — to go run it.
This router is that step's server side:

* ``GET`` says whether an owner account exists (nothing else: no username).
* ``POST`` creates it — **only while none exists**. Once there is one, the
  answer is 409 and the terminal command (or a future signed-in settings
  page) is the way to change it, so the open first-run gate can never be
  used to *replace* an owner's password. The store keeps exactly one owner
  by construction (MASTERPLAN §5.5's one-door rule).

The browser that creates the account is signed in on the spot: the account's
existence is what latches the admin gate closed
(:func:`palaia_hub.admin_session.sign_in_configured`), and without a session
the very next wizard call would bounce to the login page mid-setup.

Two things bound the exposure of a POST that, by design, needs no session:

* it works only on a hub with **no** owner — the state in which every
  ``/api/*`` route is already reachable to whoever reaches the hub at all
  (the zero-config first run the admin gate deliberately allows);
* a browser fetch carries ``Sec-Fetch-Site``; anything but a same-origin
  request is refused, so a page on another site cannot plant an owner
  password into a fresh hub through the operator's browser.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .errors import OAuthError
from .login import CSRF_COOKIE, SESSION_COOKIE, new_csrf_token, set_owner_password
from .service import AuthorizationServer

logger = logging.getLogger("palaia_hub.oauth.owner_api")

OWNER_PATH = "/api/auth/owner"

#: ``Sec-Fetch-Site`` values a browser sends for a request this hub's own
#: pages made. ``none`` is a user-initiated navigation (typed URL, bookmark).
_SAME_SITE_FETCHES = frozenset({"same-origin", "same-site", "none"})


class OwnerAccountState(BaseModel):
    """Whether the hub has an owner account. Deliberately nothing more."""

    model_config = ConfigDict(extra="forbid")

    configured: bool


class CreateOwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


def build_owner_router(server: AuthorizationServer) -> APIRouter:
    """Build the owner-account router, backed by ``server``'s store."""
    router = APIRouter(tags=["auth"])
    secure_cookies = server.issuer.startswith("https://")

    @router.get(OWNER_PATH, response_model=OwnerAccountState)
    async def owner_state() -> OwnerAccountState:
        return OwnerAccountState(configured=server.store.get_owner() is not None)

    @router.post(OWNER_PATH, response_model=OwnerAccountState, status_code=201)
    async def create_owner(
        body: CreateOwnerRequest, request: Request, response: Response
    ) -> OwnerAccountState:
        """Create the one owner account and sign this browser in.

        409 once an account exists; 403 for a request another site's page
        made through this browser.
        """
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if fetch_site and fetch_site not in _SAME_SITE_FETCHES:
            raise HTTPException(
                status_code=403,
                detail="the owner account can only be created from this hub's own pages.",
            )
        if server.store.get_owner() is not None:
            raise HTTPException(
                status_code=409,
                detail="this hub already has an owner account. Fix: to change its "
                "password, run `palaia-hub oauth set-password` where the hub runs.",
            )
        try:
            await asyncio.to_thread(
                set_owner_password,
                server.store,
                body.username,
                body.password,
                now=server.now(),
            )
            session, expires_at = await asyncio.to_thread(
                server.sign_in, body.username.strip(), body.password
            )
        except OAuthError as exc:
            raise HTTPException(status_code=400, detail=exc.description) from exc
        max_age = max(0, expires_at - server.now())
        response.set_cookie(
            SESSION_COOKIE,
            session,
            max_age=max_age,
            path="/",
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
        )
        # Readable on purpose — the dashboard echoes it in X-Palaia-CSRF
        # (same pair `/oauth/login` sets; see routes._start_session).
        response.set_cookie(
            CSRF_COOKIE,
            new_csrf_token(),
            max_age=max_age,
            path="/",
            httponly=False,
            secure=secure_cookies,
            samesite="lax",
        )
        logger.info("owner account created from the first-run wizard")
        return OwnerAccountState(configured=True)

    return router


__all__ = ["OWNER_PATH", "CreateOwnerRequest", "OwnerAccountState", "build_owner_router"]
