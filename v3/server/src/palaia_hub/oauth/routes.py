"""The authorization server's HTTP surface.

Thin by design: each handler parses its request, calls one
:class:`~palaia_hub.oauth.service.AuthorizationServer` method, and serializes
the answer. No protocol decision is taken in this module, so a reviewer can
read :mod:`palaia_hub.oauth.service` for "what the rules are" and this file
only for "how they reach the wire".

Wire-level obligations handled here and nowhere else:

* ``Cache-Control: no-store`` on every response that carries or produces a
  credential (RFC 6749 §5.1) — token, authorize, login, register.
* RFC 6749 §5.2 JSON error bodies, with ``WWW-Authenticate`` on a failed
  client authentication.
* ``application/x-www-form-urlencoded`` request parsing for the token,
  revocation and login endpoints; JSON for registration.
* Cookies: ``HttpOnly``, ``SameSite=Lax``, ``Secure`` when the issuer is
  https, ``Path=/``.
* **Every store-touching call runs on a worker thread** through
  ``asyncio.to_thread``. SQLite statements and argon2 verifies are blocking;
  running them inline would serialize the whole event loop behind one token
  request, and would make the concurrency fan-out test a fiction.
* **Nothing here logs a request line, query string or form body.** An
  authorization redirect carries a code and a token request carries a
  verifier and a refresh token; the only safe policy is not to log them, which
  is why the handlers below log nothing and the service logs identifiers only.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import html
import logging
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .errors import OAuthError
from .login import CSRF_COOKIE, CSRF_FIELD, SESSION_COOKIE, new_csrf_token
from .models import ClientInfo
from .service import (
    AUTHORIZE_PATH,
    IDP_CALLBACK_PATH,
    IDP_START_PATH,
    JWKS_PATH,
    LOGIN_PATH,
    REGISTER_PATH,
    REVOKE_PATH,
    TOKEN_PATH,
    AuthorizationServer,
    AuthorizeRedirect,
    LoginRequired,
)

logger = logging.getLogger("palaia_hub.oauth.routes")

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

METADATA_PATH = "/.well-known/oauth-authorization-server"
OIDC_METADATA_PATH = "/.well-known/openid-configuration"
PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource/{profile}"
LOGOUT_PATH = "/oauth/logout"


def _error_response(exc: OAuthError) -> JSONResponse:
    return JSONResponse(
        exc.body(),
        status_code=exc.status_code,
        headers={**NO_STORE, **exc.headers},
    )


def _basic_auth(request: Request) -> tuple[str, str] | None:
    """Parse an HTTP Basic ``Authorization`` header, or ``None``.

    A malformed header is treated as absent rather than as an error: the
    caller then falls through to ``client_secret_post``, and an unauthenticated
    request ends in the same ``invalid_client`` either way.
    """
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    client_id, sep, client_secret = decoded.partition(":")
    if not sep:
        return None
    return client_id, client_secret


def _is_safe_next(next_url: str) -> bool:
    """Is ``next_url`` a local authorization-request URL we may redirect to?

    Only a path on this server, and only the authorize endpoint. Anything
    else — an absolute URL, a scheme-relative ``//evil.example``, a different
    local path — is refused, because ``next`` comes from the query string and
    an unchecked one is an open redirect with the operator's freshly minted
    session cookie attached.
    """
    parts = urlsplit(next_url)
    if parts.scheme or parts.netloc:
        return False
    return parts.path == AUTHORIZE_PATH


def _set_cookie(
    response: Response, name: str, value: str, *, secure: bool, max_age: int, http_only: bool = True
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        httponly=http_only,
        secure=secure,
        samesite="lax",
    )


def build_oauth_router(server: AuthorizationServer) -> APIRouter:
    """Build the authorization server's router, backed by ``server``."""
    secure_cookies = server.issuer.startswith("https://")
    router = APIRouter(tags=["oauth"])

    # ------------------------------------------------------------- discovery

    @router.get(METADATA_PATH)
    async def authorization_server_metadata() -> Response:
        """RFC 8414 authorization-server metadata."""
        return JSONResponse(server.metadata())

    @router.get(OIDC_METADATA_PATH)
    async def openid_configuration() -> Response:
        """The same document at the OIDC discovery path.

        MCP 2025-11-25 added OIDC Discovery as a way to find the
        authorization server, and several clients probe this path first. It is
        the identical metadata document — palaia is not an OpenID Provider and
        does not claim to be one (no ``id_token`` is ever issued); this exists
        purely so a client's first probe succeeds instead of 404ing.
        """
        return JSONResponse(server.metadata())

    @router.get(JWKS_PATH)
    async def jwks() -> Response:
        """The public signing key (RFC 7517)."""
        return JSONResponse(server.jwks())

    @router.get(PROTECTED_RESOURCE_PATH)
    async def protected_resource_metadata(profile: str) -> Response:
        """RFC 9728 protected-resource metadata for one MCP profile."""
        try:
            return JSONResponse(server.protected_resource_metadata(profile))
        except OAuthError as exc:
            return JSONResponse(exc.body(), status_code=404)

    # ------------------------------------------------------------- authorize

    @router.get(AUTHORIZE_PATH)
    async def authorize(request: Request) -> Response:
        """The authorization endpoint (code flow, PKCE mandatory)."""
        params = dict(request.query_params)
        session = request.cookies.get(SESSION_COOKIE)
        try:
            outcome = await server.authorize(params, session=session)
        except OAuthError as exc:
            # Pre-redirect-validation failure: RFC 6749 §4.1.2.1 says show the
            # user an error rather than redirecting to an unvalidated URI.
            return _authorize_error_page(exc)
        if isinstance(outcome, LoginRequired):
            # One door only (MASTERPLAN §5.5): with an IdP configured, there
            # is exactly one way in, so this goes straight to it rather than
            # through an interstitial page offering a password door that
            # does not exist.
            start = IDP_START_PATH if server.idp_configured else LOGIN_PATH
            location = f"{start}?next={_quote(outcome.next_url)}"
            return RedirectResponse(location, status_code=303, headers=NO_STORE)
        assert isinstance(outcome, AuthorizeRedirect)  # noqa: S101 - exhaustive union
        return RedirectResponse(outcome.location, status_code=303, headers=NO_STORE)

    # ----------------------------------------------------------------- token

    @router.post(TOKEN_PATH)
    async def token(request: Request) -> Response:
        """The token endpoint: authorization_code, refresh_token, client_credentials."""
        form = dict(await request.form())
        basic = _basic_auth(request)
        try:
            issued = await asyncio.to_thread(
                server.token,
                {k: v for k, v in form.items() if isinstance(v, str)},
                basic_auth=basic,
            )
        except OAuthError as exc:
            return _error_response(exc)
        body: dict[str, Any] = {
            "access_token": issued.access_token,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
            "scope": " ".join(issued.scopes),
        }
        if issued.refresh_token is not None:
            body["refresh_token"] = issued.refresh_token
        return JSONResponse(body, headers=NO_STORE)

    @router.post(REVOKE_PATH)
    async def revoke(request: Request) -> Response:
        """RFC 7009 revocation: 200 whether or not the token existed."""
        form = dict(await request.form())
        try:
            await asyncio.to_thread(
                server.revoke, {k: v for k, v in form.items() if isinstance(v, str)}
            )
        except OAuthError as exc:
            return _error_response(exc)
        return Response(status_code=200, headers=NO_STORE)

    @router.post(REGISTER_PATH)
    async def register(request: Request) -> Response:
        """RFC 7591 dynamic client registration (deprecated; CIMD is preferred)."""
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _error_response(
                OAuthError("invalid_client_metadata", "the request body must be JSON.")
            )
        try:
            client = await asyncio.to_thread(server.register, body)
        except OAuthError as exc:
            return _error_response(exc)
        info = ClientInfo.from_row(client)
        return JSONResponse(
            {
                "client_id": info.client_id,
                "client_id_issued_at": info.created_at,
                "client_name": info.client_name,
                "redirect_uris": info.redirect_uris,
                "grant_types": info.grant_types,
                "token_endpoint_auth_method": "none",
                "scope": " ".join(info.scopes),
            },
            status_code=201,
            headers=NO_STORE,
        )

    # ----------------------------------------------------------------- login
    #
    # One door only (MASTERPLAN §5.5, SPEC-204 deliverable #3): neither of
    # these routes is registered when an IdP is configured. `authorize()`
    # above sends an unauthenticated browser straight to the IdP flow in
    # that case, so there is no interstitial page offering a password door
    # that does not exist — and a request to either verb here 404s exactly
    # like any other path this server never served, rather than 403ing
    # (which would still confirm the door exists, just locked).

    if not server.idp_configured:

        @router.get(LOGIN_PATH)
        async def login_form(request: Request) -> Response:
            """The owner sign-in form."""
            next_url = request.query_params.get("next", "")
            csrf = new_csrf_token()
            response = HTMLResponse(
                _login_page(
                    next_url=next_url if _is_safe_next(next_url) else "", csrf=csrf, error=""
                ),
                headers=NO_STORE,
            )
            _set_cookie(response, CSRF_COOKIE, csrf, secure=secure_cookies, max_age=600)
            return response

        @router.post(LOGIN_PATH)
        async def login_submit(request: Request) -> Response:
            """Verify the owner's password, open a session, continue to ``next``."""
            form = dict(await request.form())
            next_url = str(form.get("next", "") or "")
            submitted_csrf = str(form.get(CSRF_FIELD, "") or "")
            cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
            if not cookie_csrf or submitted_csrf != cookie_csrf:
                # Double-submit mismatch: either a stale form or a cross-site POST.
                return _login_failure(
                    next_url,
                    "This sign-in form expired. Please try again.",
                    secure=secure_cookies,
                )
            username = str(form.get("username", "") or "")
            password = str(form.get("password", "") or "")
            try:
                session, expires_at = await asyncio.to_thread(server.sign_in, username, password)
            except OAuthError:
                return _login_failure(
                    next_url,
                    "Sign-in failed. Check the username and password.",
                    secure=secure_cookies,
                )
            target = next_url if _is_safe_next(next_url) else "/"
            response = RedirectResponse(target, status_code=303, headers=NO_STORE)
            _set_cookie(
                response,
                SESSION_COOKIE,
                session,
                secure=secure_cookies,
                max_age=max(0, expires_at - server.now()),
            )
            response.delete_cookie(CSRF_COOKIE, path="/")
            return response

    # ------------------------------------------------------------- idp (204)

    if server.idp_configured:

        @router.get(IDP_START_PATH)
        async def idp_start(request: Request) -> Response:
            """Redirect the browser to the configured provider."""
            next_url = request.query_params.get("next", "")
            if not _is_safe_next(next_url):
                return _authorize_error_page(
                    OAuthError(
                        "invalid_request",
                        "this sign-in link is invalid. Fix: start from the sign-in page.",
                    )
                )
            location = await server.start_idp_signin(next_url)
            return RedirectResponse(location, status_code=303, headers=NO_STORE)

        @router.get(IDP_CALLBACK_PATH)
        async def idp_callback(request: Request) -> Response:
            """The provider sends the browser back here with ``code``/``state``."""
            params = dict(request.query_params)
            try:
                session, expires_at, next_url = await server.finish_idp_signin(params)
            except OAuthError as exc:
                return _authorize_error_page(exc)
            target = next_url if _is_safe_next(next_url) else "/"
            response = RedirectResponse(target, status_code=303, headers=NO_STORE)
            _set_cookie(
                response,
                SESSION_COOKIE,
                session,
                secure=secure_cookies,
                max_age=max(0, expires_at - server.now()),
            )
            return response

    @router.post(LOGOUT_PATH)
    async def logout(request: Request) -> Response:
        """Drop the browser session (the sign-in half of a revocation UI)."""
        await asyncio.to_thread(server.sign_out, request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    return router


# ------------------------------------------------------------------- rendering


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _login_failure(next_url: str, message: str, *, secure: bool) -> Response:
    """Re-render the form with a message and a fresh CSRF token.

    One message for every failure reason (wrong username, wrong password, no
    account configured, expired form) — see
    :func:`palaia_hub.oauth.login.verify_owner_password`.
    """
    csrf = new_csrf_token()
    response = HTMLResponse(
        _login_page(
            next_url=next_url if _is_safe_next(next_url) else "", csrf=csrf, error=message
        ),
        status_code=401,
        headers=NO_STORE,
    )
    _set_cookie(response, CSRF_COOKIE, csrf, secure=secure, max_age=600)
    return response


def _authorize_error_page(exc: OAuthError) -> Response:
    """Render a pre-redirect authorization error for the person in the browser."""
    return HTMLResponse(
        _PAGE_TEMPLATE.format(
            title="Cannot continue",
            body=(
                f"<h1>Cannot continue</h1>"
                f"<p class='err'>{html.escape(exc.error)}</p>"
                f"<p>{html.escape(exc.description)}</p>"
            ),
        ),
        status_code=exc.status_code,
        headers=NO_STORE,
    )


def _login_page(*, next_url: str, csrf: str, error: str) -> str:
    error_block = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    return _PAGE_TEMPLATE.format(
        title="Sign in to palaia",
        body=(
            "<h1>Sign in to palaia</h1>"
            f"{error_block}"
            f'<form method="post" action="{html.escape(LOGIN_PATH)}">'
            '<label>Username<input name="username" autocomplete="username" autofocus></label>'
            '<label>Password<input name="password" type="password" '
            'autocomplete="current-password"></label>'
            f'<input type="hidden" name="{CSRF_FIELD}" value="{html.escape(csrf)}">'
            f'<input type="hidden" name="next" value="{html.escape(next_url)}">'
            '<button type="submit">Sign in</button>'
            "</form>"
            "<p class='hint'>The hub's operator sets this password with "
            "<code>palaia-hub oauth set-password</code>.</p>"
        ),
    )


#: Deliberately one self-contained page with no external assets: this form is
#: served before any session exists, so it must not depend on the dashboard
#: build being present, and it must not load anything from a third party.
_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 system-ui, sans-serif; margin: 0; display: grid;
          place-items: center; min-height: 100vh; }}
  main {{ width: min(22rem, 92vw); padding: 2rem 0; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
  label {{ display: block; margin-bottom: .75rem; font-size: .875rem; }}
  input {{ display: block; width: 100%; padding: .5rem; margin-top: .25rem;
           font: inherit; box-sizing: border-box; }}
  button {{ padding: .5rem 1rem; font: inherit; }}
  .err {{ color: #b00020; font-size: .875rem; }}
  .hint {{ font-size: .8125rem; opacity: .7; }}
  code {{ font-size: .8125rem; }}
</style></head>
<body><main>{body}</main></body></html>
"""


__all__ = [
    "LOGOUT_PATH",
    "METADATA_PATH",
    "OIDC_METADATA_PATH",
    "PROTECTED_RESOURCE_PATH",
    "build_oauth_router",
]
