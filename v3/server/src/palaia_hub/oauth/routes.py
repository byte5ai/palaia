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
from secrets import compare_digest
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .errors import OAuthError
from .login import (
    CSRF_COOKIE,
    CSRF_FIELD,
    CSRF_HEADER,
    IDP_NONCE_COOKIE,
    SESSION_COOKIE,
    new_csrf_token,
)
from .models import ClientInfo
from .service import (
    AUTHORIZE_PATH,
    IDP_CALLBACK_PATH,
    IDP_START_PATH,
    IDP_STATE_TTL_SECONDS,
    JWKS_PATH,
    LOGIN_PATH,
    REGISTER_PATH,
    REVOKE_PATH,
    TOKEN_PATH,
    AuthorizationServer,
    AuthorizeOutcome,
    AuthorizeRedirect,
    ConsentRequired,
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


#: Path prefixes a ``next`` may never point at. These are backend surfaces,
#: not pages: sending a freshly signed-in browser to one of them would at
#: best show it JSON and at worst replay a state-changing call, so the only
#: paths worth continuing to are the authorization endpoint and the
#: dashboard's own client-side routes.
_NEVER_NEXT_PREFIXES = ("/api/", "/oauth/", "/mcp/")


def _is_safe_next(next_url: str) -> bool:
    """Is ``next_url`` a local URL we may redirect a signed-in browser to?

    Two kinds are allowed, and nothing else: the authorization endpoint (the
    SPEC-203 flow's own continuation) and a dashboard page — a path on this
    server that is not one of this hub's backend surfaces (SPEC-401: the
    dashboard's sign-in redirect has to be able to come back to the screen
    the operator was on). An absolute URL, a scheme-relative
    ``//evil.example``, or anything not starting with a single ``/`` is
    refused, because ``next`` comes from the query string and an unchecked
    one is an open redirect with the operator's freshly minted session cookie
    attached.
    """
    parts = urlsplit(next_url)
    if parts.scheme or parts.netloc:
        return False
    path = parts.path
    if path == AUTHORIZE_PATH:
        return True
    if not path.startswith("/") or path.startswith("//"):
        return False
    return not any(
        path == prefix.rstrip("/") or path.startswith(prefix) for prefix in _NEVER_NEXT_PREFIXES
    )


def request_is_https(request: Request) -> bool:
    """Did this request reach the hub over HTTPS?

    Decides the cookies' ``Secure`` flag per request, not from the issuer: in
    Cloud mode the issuer is the public https address, while the owner signs
    in to the dashboard over the private network's plain http — and a browser
    drops a ``Secure`` cookie set over http, which turned every dashboard
    sign-in into a loop. Behind the packaged nginx (and any TLS-terminating
    tunnel or proxy) the scheme arrives as ``X-Forwarded-Proto``.
    """
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


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


def _start_session(target: str, *, session: str, max_age: int, secure: bool) -> RedirectResponse:
    """Redirect to ``target`` carrying a fresh session and its CSRF token.

    Both doors (password, provider) end here, so the pair is always set
    together. The session cookie is ``HttpOnly``; the CSRF cookie
    deliberately is **not** — the dashboard has to read it to echo it in the
    ``X-Palaia-CSRF`` header that :class:`palaia_hub.admin_session.
    AdminSessionMiddleware` requires on every state-changing REST call
    (SPEC-401 deliverable #3, the same double-submit pattern the sign-in form
    itself uses). A readable CSRF token is not a weakness: what a
    double-submit token proves is that the caller can both *read* a value
    from this origin and *set a header*, neither of which another site can
    do. Its lifetime matches the session's, so an expired session never
    leaves a stale token behind that outlives it.
    """
    response = RedirectResponse(target, status_code=303, headers=NO_STORE)
    _set_cookie(response, SESSION_COOKIE, session, secure=secure, max_age=max_age)
    _set_cookie(
        response,
        CSRF_COOKIE,
        new_csrf_token(),
        secure=secure,
        max_age=max_age,
        http_only=False,
    )
    return response


def build_oauth_router(server: AuthorizationServer) -> APIRouter:
    """Build the authorization server's router, backed by ``server``."""
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

    def _login_hop(outcome: LoginRequired) -> Response:
        # One door only (MASTERPLAN §5.5): with an IdP configured, there
        # is exactly one way in, so this goes straight to it rather than
        # through an interstitial page offering a password door that
        # does not exist.
        start = IDP_START_PATH if server.idp_configured else LOGIN_PATH
        location = f"{start}?next={_quote(outcome.next_url)}"
        return RedirectResponse(location, status_code=303, headers=NO_STORE)

    def _authorize_outcome(outcome: AuthorizeOutcome, request: Request) -> Response:
        if isinstance(outcome, LoginRequired):
            return _login_hop(outcome)
        if isinstance(outcome, ConsentRequired):
            # Issue #328: nothing is minted on a GET. The page's form echoes
            # the reviewed request and the session's CSRF token; only the
            # POST below issues a code.
            return HTMLResponse(
                _consent_page(outcome, csrf=request.cookies.get(CSRF_COOKIE, "")),
                headers=NO_STORE,
            )
        assert isinstance(outcome, AuthorizeRedirect)  # noqa: S101 - exhaustive union
        return RedirectResponse(outcome.location, status_code=303, headers=NO_STORE)

    @router.get(AUTHORIZE_PATH)
    async def authorize(request: Request) -> Response:
        """The authorization endpoint (code flow, PKCE mandatory): validate,
        then ask the signed-in owner (issue #328)."""
        params = dict(request.query_params)
        session = request.cookies.get(SESSION_COOKIE)
        try:
            outcome = await server.authorize(params, session=session)
        except OAuthError as exc:
            # Pre-redirect-validation failure: RFC 6749 §4.1.2.1 says show the
            # user an error rather than redirecting to an unvalidated URI.
            return _authorize_error_page(exc)
        return _authorize_outcome(outcome, request)

    @router.post(AUTHORIZE_PATH)
    async def authorize_decide(request: Request) -> Response:
        """The owner's answer to the consent page (issue #328).

        Double-submit CSRF: the ``csrf_token`` field must equal the session's
        CSRF cookie, which only a page served from this origin can read — a
        cross-site form post cannot supply it, so a crafted link can still
        only *show* the page, never answer it.
        """
        form = dict(await request.form())
        submitted = str(form.get(CSRF_FIELD, "") or "")
        cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
        if not cookie_csrf or not submitted or not compare_digest(submitted, cookie_csrf):
            return _authorize_error_page(
                OAuthError(
                    "invalid_request",
                    "This answer could not be confirmed as coming from the consent "
                    "page in your own browser session. Fix: reopen the connect link "
                    "from your AI tool and answer again.",
                    status_code=403,
                )
            )
        decision = str(form.get("decision", "") or "")
        params = {
            k: v
            for k, v in form.items()
            if isinstance(v, str) and k not in (CSRF_FIELD, "decision")
        }
        session = request.cookies.get(SESSION_COOKIE)
        try:
            outcome = await server.authorize(params, session=session, decision=decision)
        except OAuthError as exc:
            return _authorize_error_page(exc)
        return _authorize_outcome(outcome, request)

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
            _set_cookie(response, CSRF_COOKIE, csrf, secure=request_is_https(request), max_age=600)
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
                    secure=request_is_https(request),
                )
            username = str(form.get("username", "") or "")
            password = str(form.get("password", "") or "")
            try:
                session, expires_at = await asyncio.to_thread(server.sign_in, username, password)
            except OAuthError:
                return _login_failure(
                    next_url,
                    "Sign-in failed. Check the username and password.",
                    secure=request_is_https(request),
                )
            target = next_url if _is_safe_next(next_url) else "/"
            # The login form's own short-lived CSRF cookie is replaced here
            # (not deleted) by the session-lifetime one the dashboard reads —
            # see _start_session.
            return _start_session(
                target,
                session=session,
                max_age=max(0, expires_at - server.now()),
                secure=request_is_https(request),
            )

    # ------------------------------------------------------------- idp (204)

    if server.idp_configured:

        @router.get(IDP_START_PATH)
        async def idp_start(request: Request) -> Response:
            """Redirect the browser to the configured provider."""
            # Issue #381: a start with no `next` (the dashboard's sign-out
            # lands here, and so does a bookmark) means "sign in, then Home".
            next_url = request.query_params.get("next") or "/"
            if not _is_safe_next(next_url):
                return _authorize_error_page(
                    OAuthError(
                        "invalid_request",
                        "this sign-in link is invalid. Fix: start from the sign-in page.",
                    )
                )
            # Issue #345: the browser that starts the sign-in is the only one
            # that may finish it — a nonce cookie here, its hash on the ticket.
            nonce = new_csrf_token()
            location = await server.start_idp_signin(next_url, browser_nonce=nonce)
            response = RedirectResponse(location, status_code=303, headers=NO_STORE)
            _set_cookie(
                response,
                IDP_NONCE_COOKIE,
                nonce,
                secure=request_is_https(request),
                max_age=IDP_STATE_TTL_SECONDS,
            )
            return response

        @router.get(IDP_CALLBACK_PATH)
        async def idp_callback(request: Request) -> Response:
            """The provider sends the browser back here with ``code``/``state``."""
            params = dict(request.query_params)
            nonce = request.cookies.get(IDP_NONCE_COOKIE, "")
            try:
                session, expires_at, next_url = await server.finish_idp_signin(
                    params, browser_nonce=nonce
                )
            except OAuthError as exc:
                failure = _authorize_error_page(exc)
                failure.delete_cookie(IDP_NONCE_COOKIE, path="/")
                return failure
            target = next_url if _is_safe_next(next_url) else "/"
            response = _start_session(
                target,
                session=session,
                max_age=max(0, expires_at - server.now()),
                secure=request_is_https(request),
            )
            response.delete_cookie(IDP_NONCE_COOKIE, path="/")
            return response

    @router.post(LOGOUT_PATH)
    async def logout(request: Request) -> Response:
        """Drop the browser session (the sign-in half of a revocation UI).

        Double-submit protected like every other state-changing call
        (SPEC-502): signing out lives at ``/oauth/logout``, outside the
        ``/api/*`` prefix :class:`palaia_hub.admin_session.
        AdminSessionMiddleware` covers, so before this SPEC any page on the
        internet could sign the operator out of their own hub with a form
        post. That is a nuisance rather than a breach — but it is a
        state-changing surface with no token on it, and the SPEC's rule is
        that there are none of those.

        The token is accepted from the ``X-Palaia-CSRF`` header (what the
        dashboard's API client sends) or from a ``csrf_token`` form field
        (what a plain HTML sign-out button would send), and must equal the
        cookie the sign-in flow set.
        """
        cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
        submitted = request.headers.get(CSRF_HEADER, "")
        if not submitted and "form" in request.headers.get("content-type", ""):
            submitted = str(dict(await request.form()).get(CSRF_FIELD, "") or "")
        if not cookie_csrf or not submitted or not compare_digest(submitted, cookie_csrf):
            return JSONResponse(
                {
                    "detail": (
                        "This sign-out request could not be confirmed as coming "
                        "from the dashboard. Please reload the page and try again."
                    )
                },
                status_code=403,
                headers=NO_STORE,
            )
        await asyncio.to_thread(server.sign_out, request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204, headers=NO_STORE)
        response.delete_cookie(SESSION_COOKIE, path="/")
        # The CSRF token is part of the session (see _start_session), so it
        # goes with it — leaving it behind would hand the next visitor on
        # this browser a token for a session that no longer exists.
        response.delete_cookie(CSRF_COOKIE, path="/")
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
        _login_page(next_url=next_url if _is_safe_next(next_url) else "", csrf=csrf, error=message),
        status_code=401,
        headers=NO_STORE,
    )
    _set_cookie(response, CSRF_COOKIE, csrf, secure=secure, max_age=600)
    return response


def _authorize_error_page(exc: OAuthError) -> Response:
    """Render a pre-redirect authorization error for the person in the browser."""
    return HTMLResponse(
        _PAGE_TEMPLATE.format(
            title="Can't continue",
            body=(
                "<h1>Can't continue</h1>"
                f"<p>{html.escape(exc.description)}</p>"
                f"<p class='hint'>Error code: <code>{html.escape(exc.error)}</code></p>"
            ),
        ),
        status_code=exc.status_code,
        headers=NO_STORE,
    )


def _describe_scope(scope: str) -> str:
    """One plain-language line per scope, for the consent page (issue #328)."""
    parts = scope.split(":")
    if len(parts) == 3 and parts[0] == "vault":
        verb = "Read" if parts[2] == "read" else "Save into"
        return f"{verb} the \u201c{parts[1]}\u201d memory"
    if len(parts) == 2:
        family, permission = parts
        subject = {
            "stash": "the shared scratch space",
            "directory": "the session directory",
            "messenger": "the messenger",
            "telegram": "your Telegram bots",
        }.get(family, family)
        verb = {"read": "Read", "write": "Change", "send": "Send through"}.get(
            permission, permission.capitalize()
        )
        return f"{verb} {subject}"
    return scope


def _consent_page(outcome: ConsentRequired, *, csrf: str) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
        for name, value in outcome.params.items()
    )
    scope_items = (
        "".join(
            f'<li title="{html.escape(scope)}">{html.escape(_describe_scope(scope))}</li>'
            for scope in outcome.scopes
        )
        or "<li>Nothing in particular: the app asked for no permissions.</li>"
    )
    target = urlsplit(outcome.redirect_uri)
    where = html.escape(f"{target.scheme}://{target.netloc}")
    return _PAGE_TEMPLATE.format(
        title="Allow this AI app?",
        body=(
            "<h1>Allow this AI app?</h1>"
            f"<p><strong>{html.escape(outcome.client_name)}</strong> wants to use your palaia. "
            "If you allow it, it may:</p>"
            f"<ul>{scope_items}</ul>"
            f"<p class='hint'>Afterwards your browser goes back to <code>{where}</code>. "
            "If you didn't just start connecting an AI app, choose Deny.</p>"
            f'<form method="post" action="{html.escape(AUTHORIZE_PATH)}">'
            f"{hidden}"
            f'<input type="hidden" name="{CSRF_FIELD}" value="{html.escape(csrf)}">'
            '<div class="actions">'
            '<button type="submit" name="decision" value="allow" autofocus>Allow</button>'
            '<button type="submit" name="decision" value="deny" class="secondary">Deny</button>'
            "</div>"
            "</form>"
        ),
    )


def _login_page(*, next_url: str, csrf: str, error: str) -> str:
    error_block = f"<p class='err' role='alert'>{html.escape(error)}</p>" if error else ""
    return _PAGE_TEMPLATE.format(
        title="Sign in to palaia",
        body=(
            "<h1>Sign in to palaia</h1>"
            f"{error_block}"
            f'<form method="post" action="{html.escape(LOGIN_PATH)}">'
            '<label>Username<input name="username" autocomplete="username" autofocus '
            "required></label>"
            '<label>Password<input name="password" type="password" '
            'autocomplete="current-password" required></label>'
            f'<input type="hidden" name="{CSRF_FIELD}" value="{html.escape(csrf)}">'
            f'<input type="hidden" name="next" value="{html.escape(next_url)}">'
            '<div class="actions"><button type="submit">Sign in</button></div>'
            "</form>"
            "<details><summary>Forgot your password?</summary>"
            "<p class='hint'>Set a new one on the server palaia runs on:</p>"
            "<p class='cmd'><code>palaia-hub oauth set-password --username &lt;name&gt;</code></p>"
            "<p class='hint'>With Docker:</p>"
            "<p class='cmd'><code>docker exec -it palaia-hub palaia-hub oauth set-password "
            "--username &lt;name&gt;</code></p>"
            "</details>"
        ),
    )


#: The design tokens these pages use, as (light, dark) — the values of
#: v3/design/tokens.json, which a test compares them with. The pages cannot
#: load the dashboard's stylesheet or fonts: they are served before any
#: session exists, possibly without a dashboard build, under
#: OAUTH_PAGE_CSP (inline styles only, nothing fetched).
_PAGE_COLORS: dict[str, tuple[str, str]] = {
    "canvas": ("#F5F7FA", "#0F1520"),
    "surface": ("#FFFFFF", "#161D2A"),
    "surface-muted": ("#EEF1F5", "#1C2433"),
    "border": ("#E3E7ED", "#263043"),
    "text": ("#1D232C", "#E8ECF1"),
    "text-2": ("#4B5563", "#AEB6C2"),
    "text-3": ("#667080", "#8B95A3"),
    "brand": ("#009FE3", "#009FE3"),
    "action": ("#0369A1", "#38BDF8"),
    "action-hover": ("#04618F", "#7DD3FC"),
    "on-action": ("#FFFFFF", "#0A0F1A"),
    "focus": ("#0369A1", "#009FE3"),
    "error": ("#B91C1C", "#F87171"),
    "error-bg": ("#F8E8E8", "#3A2A35"),
}


def _color_vars(index: int) -> str:
    return " ".join(f"--{name}: {values[index]};" for name, values in _PAGE_COLORS.items())


_PAGE_STYLE = f"""
  :root {{ color-scheme: light; {_color_vars(0)} }}
  @media (prefers-color-scheme: dark) {{ :root {{ color-scheme: dark; {_color_vars(1)} }} }}
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
          background: var(--canvas); color: var(--text);
          font: 15px/24px "Nunito Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
          -webkit-font-smoothing: antialiased; }}
  main {{ width: min(420px, calc(100vw - 32px)); padding: 32px 0; }}
  .brand {{ display: flex; align-items: center; gap: 10px; margin: 0 0 24px 4px;
            font: 400 20px/28px "Days One", "Nunito Sans", system-ui, sans-serif; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
           padding: 24px; box-shadow: 0 1px 2px rgba(15, 21, 32, .06); }}
  h1 {{ font-size: 28px; line-height: 34px; font-weight: 700; margin: 0 0 20px; }}
  p {{ margin: 0 0 12px; }}
  ul {{ margin: 0 0 16px; padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  label {{ display: block; margin: 0 0 16px; font-weight: 600; }}
  input {{ display: block; width: 100%; height: 40px; margin-top: 8px; padding: 0 12px;
           border: 1px solid var(--text-3); border-radius: 10px; background: var(--surface);
           color: var(--text); font: inherit; font-weight: 400; }}
  .actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }}
  button {{ height: 40px; padding: 0 20px; border-radius: 999px; border: 1px solid var(--action);
            background: var(--action); color: var(--on-action); font: inherit; font-weight: 600;
            cursor: pointer; }}
  button:hover {{ background: var(--action-hover); border-color: var(--action-hover); }}
  button.secondary {{ background: var(--surface); color: var(--text);
                      border-color: var(--border); }}
  button.secondary:hover {{ background: var(--surface-muted); }}
  :focus-visible {{ outline: 2px solid var(--focus); outline-offset: 2px; }}
  .err {{ padding: 12px 16px; border-radius: 14px; background: var(--error-bg); color: var(--error);
          font-size: 13px; line-height: 20px; font-weight: 600; }}
  .hint {{ font-size: 13px; line-height: 20px; color: var(--text-2); }}
  details {{ margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }}
  summary {{ cursor: pointer; color: var(--action); font-size: 13px; font-weight: 600; }}
  details[open] summary {{ margin-bottom: 12px; }}
  code {{ font: 13px/20px ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace;
          background: var(--surface-muted); padding: 1px 6px; border-radius: 6px;
          overflow-wrap: anywhere; }}
  .cmd code {{ display: block; padding: 8px 12px; border-radius: 10px; }}
"""

#: The palaia star — the website header's mark, inline (no request).
_PAGE_MARK = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    '<circle cx="12" cy="12" r="3" fill="var(--brand)"/>'
    '<g stroke="var(--brand)" stroke-opacity="0.5" stroke-width="1.3">'
    '<line x1="12" y1="12" x2="12" y2="3"/><line x1="12" y1="12" x2="20" y2="8"/>'
    '<line x1="12" y1="12" x2="19" y2="18"/><line x1="12" y1="12" x2="5" y2="18"/>'
    '<line x1="12" y1="12" x2="4" y2="8"/></g>'
    '<g fill="var(--brand)" fill-opacity="0.85">'
    '<circle cx="12" cy="3" r="1.7"/><circle cx="20" cy="8" r="1.7"/>'
    '<circle cx="19" cy="18" r="1.7"/><circle cx="5" cy="18" r="1.7"/>'
    '<circle cx="4" cy="8" r="1.7"/></g></svg>'
)


def _escape_braces(text: str) -> str:
    return text.replace("{", "{{").replace("}", "}}")


#: Deliberately one self-contained page with no external assets: this form is
#: served before any session exists, so it must not depend on the dashboard
#: build being present, and it must not load anything from a third party.
#: Styled with the design system's tokens (v3/docs/design/system.md); fonts
#: fall back to the system's own when Nunito Sans is not installed.
_PAGE_TEMPLATE = (
    "<!doctype html>\n"
    '<html lang="en"><head><meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="referrer" content="no-referrer">\n'
    '<meta name="color-scheme" content="light dark">\n'
    "<title>{title}</title>\n"
    f"<style>{_escape_braces(_PAGE_STYLE)}</style></head>\n"
    f'<body><main><div class="brand">{_escape_braces(_PAGE_MARK)}<span>palaia</span></div>'
    '<div class="card">{body}</div></main></body></html>\n'
)


__all__ = [
    "LOGOUT_PATH",
    "METADATA_PATH",
    "OIDC_METADATA_PATH",
    "PROTECTED_RESOURCE_PATH",
    "build_oauth_router",
]
