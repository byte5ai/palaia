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

Issue #561: the router is mounted on a hub *without* a running sign-in server
too, writing the account straight into the store the server reads once it is
switched on. The first-run wizard can then create the account before cloud
access (which turns the server on, and needs a restart) instead of sending
the owner back to this step afterwards. No session is opened then — there is
no server to resolve one against, and no admin gate to pass either.

Two things bound the exposure of a POST that, by design, needs no session:

* it works only on a hub with **no** owner — the state in which every
  ``/api/*`` route is already reachable to whoever reaches the hub at all
  (the zero-config first run the admin gate deliberately allows);
* like every change under ``/api/*``, it is accepted only as JSON and
  never from a request a browser marks as coming from another site
  (:mod:`palaia_hub.security.cross_site`, issue #587), so a page on another
  site cannot plant an owner password into a fresh hub through the
  operator's browser.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .errors import OAuthError
from .keys import now_seconds
from .login import CSRF_COOKIE, SESSION_COOKIE, new_csrf_token, set_owner_password
from .routes import request_is_https
from .service import AuthorizationServer
from .store import OAuthStore

logger = logging.getLogger("palaia_hub.oauth.owner_api")

OWNER_PATH = "/api/auth/owner"


class OwnerAccountState(BaseModel):
    """Whether the hub has an owner account. Deliberately nothing more."""

    model_config = ConfigDict(extra="forbid")

    configured: bool


class CreateOwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


def build_owner_router(
    server: AuthorizationServer | None, *, home: Path | None = None
) -> APIRouter:
    """Build the owner-account router, backed by ``server``'s store.

    ``server`` is ``None`` on a hub whose sign-in server is off: the router
    then opens the store under ``home`` itself, on first use.
    """
    if server is None and home is None:
        raise ValueError("build_owner_router needs a server or a home directory")
    router = APIRouter(tags=["auth"])
    own_store: list[OAuthStore] = []
    lock = threading.Lock()

    def store() -> OAuthStore:
        if server is not None:
            return server.store
        with lock:
            if not own_store:
                opened = OAuthStore(home)  # type: ignore[arg-type]
                opened.open()
                own_store.append(opened)
            return own_store[0]

    @router.get(OWNER_PATH, response_model=OwnerAccountState)
    async def owner_state() -> OwnerAccountState:
        return OwnerAccountState(configured=store().get_owner() is not None)

    @router.post(OWNER_PATH, response_model=OwnerAccountState, status_code=201)
    async def create_owner(
        body: CreateOwnerRequest, request: Request, response: Response
    ) -> OwnerAccountState:
        """Create the one owner account and sign this browser in.

        409 once an account exists. A request another site's page made
        through this browser never gets here (``security.cross_site``).
        """
        if store().get_owner() is not None:
            raise HTTPException(
                status_code=409,
                detail="this hub already has an owner account. Fix: to change its "
                "password, run `palaia-hub oauth set-password` where the hub runs.",
            )
        try:
            await asyncio.to_thread(
                set_owner_password,
                store(),
                body.username,
                body.password,
                now=server.now() if server is not None else now_seconds(),
            )
            if server is None:
                logger.info("owner account created from the first-run wizard (sign-in off)")
                return OwnerAccountState(configured=True)
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
            secure=request_is_https(request),
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
            secure=request_is_https(request),
            samesite="lax",
        )
        logger.info("owner account created from the first-run wizard")
        return OwnerAccountState(configured=True)

    return router


__all__ = ["OWNER_PATH", "CreateOwnerRequest", "OwnerAccountState", "build_owner_router"]
