"""GitHub and generic-OIDC sign-in (SPEC-204).

Two providers, one discipline, both stated in MASTERPLAN §5.5 and enforced
here rather than merely documented:

* **Zero scopes.** GitHub's authorization request asks for none — an
  unscoped token still resolves the signed-in username through
  ``GET /user``, which is all this flow ever needs. A generic OIDC provider
  cannot go quite as low (``openid`` is mandatory to get a token at all,
  and ``profile`` is requested so the user-info response actually carries a
  username claim), but nothing beyond that.
* **The provider's token is read once and discarded.** It exists only inside
  :meth:`IdpProvider.resolve_username`'s stack frame; nothing in this module
  or its callers ever assigns it anywhere that outlives that call, and the
  authorization server never persists it (contrast with the login *session*
  id, which is this hub's own credential and is stored, hashed, in
  :class:`palaia_hub.oauth.store.OAuthStore`).

Both providers speak through :class:`IdpHttp`, an injectable seam so tests
exercise the whole exchange with no outbound network call (see
:class:`StaticIdpHttp`) while production uses :class:`HttpxIdpHttp`.

**On SSRF hardening.** :mod:`palaia_hub.oauth.cimd` fetches a URL an
unauthenticated caller supplies (a client's declared ``client_id``), so it
goes through fastmcp's DNS-pinned ``ssrf_safe_fetch``. The targets here are
different in kind: GitHub's endpoints are hardcoded constants, and the OIDC
discovery URL is set by the hub's own operator in ``config.yaml``, not by
an HTTP caller. That is also why they *can't* reuse ``ssrf_safe_fetch``
outright — it is GET-only, and a token exchange is a POST with a body.
:class:`HttpxIdpHttp` still keeps the cheap, always-applicable half of that
defense (https only, no redirect following, a response-size cap, a bounded
timeout); the DNS-pinning half is not reimplemented here. This is a
deliberate, least-deviation choice — called out in the PR rather than
hidden — not an oversight.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from ..config import GitHubIdpSettings, IdpSettings, OidcIdpSettings
from .errors import OAuthError

logger = logging.getLogger("palaia_hub.oauth.idp")

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - a URL, not a secret
GITHUB_USER_URL = "https://api.github.com/user"

_SIGN_IN_FAILED = OAuthError(
    "access_denied",
    "sign-in failed. Fix: try again; if it keeps failing, check the hub's "
    "sign-in provider settings in config.yaml.",
)


class IdpHttp(Protocol):
    """The two outbound calls a sign-in exchange needs."""

    async def post_form(
        self, url: str, data: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]: ...

    async def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]: ...


class HttpxIdpHttp:
    """Production :class:`IdpHttp`. See the module docstring for its threat model."""

    def __init__(self, *, timeout: float = 10.0, max_bytes: int = 65536) -> None:
        self._timeout = timeout
        self._max_bytes = max_bytes

    async def post_form(
        self, url: str, data: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request("POST", url, data=dict(data), headers=headers)

    async def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", url, data=None, headers=headers)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None,
        headers: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        if not url.lower().startswith("https://"):
            raise OAuthError(
                "server_error", "the sign-in provider must be reached over https."
            )
        merged_headers = {"Accept": "application/json", **(headers or {})}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=False, verify=True
            ) as client:
                response = await client.request(method, url, data=data, headers=merged_headers)
        except httpx.HTTPError as exc:
            logger.info("sign-in provider request failed: %s", type(exc).__name__)
            raise _SIGN_IN_FAILED from exc
        if len(response.content) > self._max_bytes:
            raise OAuthError("server_error", "the sign-in provider's response was too large.")
        if response.status_code >= 400:
            logger.info("sign-in provider returned HTTP %s", response.status_code)
            raise _SIGN_IN_FAILED
        try:
            body = response.json()
        except ValueError as exc:
            raise OAuthError(
                "server_error", "the sign-in provider returned an invalid response."
            ) from exc
        if not isinstance(body, dict):
            raise OAuthError(
                "server_error", "the sign-in provider returned an unexpected response."
            )
        return body


@dataclass
class StaticIdpHttp:
    """A canned :class:`IdpHttp` for tests — no outbound network call.

    ``token_responses``/``json_responses`` are keyed by the exact URL a real
    call would hit; missing a key simulates the provider rejecting the
    request. ``calls`` records every request made, so a test can assert on
    what was (and was not) sent — e.g. that a token never appears in a log
    call site, or that a discovery document is fetched only once.
    """

    token_responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    json_responses: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    async def post_form(
        self, url: str, data: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        self.calls.append(("POST", url, dict(data)))
        if url not in self.token_responses:
            raise _SIGN_IN_FAILED
        return self.token_responses[url]

    async def get_json(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        self.calls.append(("GET", url, {}))
        if url not in self.json_responses:
            raise _SIGN_IN_FAILED
        return self.json_responses[url]


class IdpProvider(Protocol):
    """What :class:`~palaia_hub.oauth.service.AuthorizationServer` needs from a provider."""

    async def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def resolve_username(self, *, code: str, redirect_uri: str) -> str: ...


class GitHubIdpProvider:
    """"Sign in with GitHub" — zero scopes, username via ``GET /user``."""

    def __init__(self, settings: GitHubIdpSettings, http: IdpHttp) -> None:
        self._settings = settings
        self._http = http

    async def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._settings.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            # Zero scopes (SPEC-204 deliverable #1): an unscoped token still
            # resolves the signed-in username, and nothing else is needed.
            "scope": "",
            "allow_signup": "false",
        }
        return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"

    async def resolve_username(self, *, code: str, redirect_uri: str) -> str:
        token_body = await self._http.post_form(
            GITHUB_TOKEN_URL,
            {
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        access_token = token_body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise _SIGN_IN_FAILED
        try:
            user = await self._http.get_json(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        finally:
            # The provider token's only use is the call above; it is not
            # assigned anywhere else and is not returned, logged, or stored.
            del access_token
        login = user.get("login")
        if not isinstance(login, str) or not login:
            raise _SIGN_IN_FAILED
        return login


class OidcIdpProvider:
    """A generic, discovery-configured OIDC provider.

    The discovery document is fetched once and cached on this instance —
    which lives for the process's lifetime (built once in
    :class:`~palaia_hub.oauth.service.AuthorizationServer`), so a restart is
    the only time it is re-fetched.
    """

    def __init__(self, settings: OidcIdpSettings, http: IdpHttp) -> None:
        self._settings = settings
        self._http = http
        self._discovery: dict[str, Any] | None = None

    async def _discover(self) -> dict[str, Any]:
        if self._discovery is None:
            self._discovery = await self._http.get_json(self._settings.discovery_url)
        return self._discovery

    async def _endpoint(self, doc: Mapping[str, Any], key: str) -> str:
        value = doc.get(key)
        if not isinstance(value, str) or not value:
            raise OAuthError(
                "server_error",
                f"the sign-in provider's discovery document has no {key!r}.",
            )
        return value

    async def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        doc = await self._discover()
        endpoint = await self._endpoint(doc, "authorization_endpoint")
        params = {
            "client_id": self._settings.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            # The minimum that still yields a resolvable username: OIDC
            # requires 'openid', and 'profile' is what typically carries
            # preferred_username in the user-info response.
            "scope": "openid profile",
        }
        return f"{endpoint}?{urlencode(params)}"

    async def resolve_username(self, *, code: str, redirect_uri: str) -> str:
        doc = await self._discover()
        token_endpoint = await self._endpoint(doc, "token_endpoint")
        userinfo_endpoint = await self._endpoint(doc, "userinfo_endpoint")
        token_body = await self._http.post_form(
            token_endpoint,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
            },
        )
        access_token = token_body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise _SIGN_IN_FAILED
        try:
            claims = await self._http.get_json(
                userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}
            )
        finally:
            del access_token
        value = claims.get(self._settings.username_claim)
        if not isinstance(value, str) or not value:
            raise _SIGN_IN_FAILED
        return value


def build_idp_provider(settings: IdpSettings, *, http: IdpHttp) -> IdpProvider:
    """Build the one configured provider from ``settings``."""
    if settings.provider == "github":
        assert settings.github is not None  # noqa: S101 - IdpSettings validated this
        return GitHubIdpProvider(settings.github, http)
    assert settings.oidc is not None  # noqa: S101 - IdpSettings validated this
    return OidcIdpProvider(settings.oidc, http)


#: Case-folded set membership check, shared by the service layer. GitHub
#: usernames and most OIDC username claims are themselves case-insensitive,
#: so this matches the provider's own notion of identity.
def is_allowed_user(username: str, allowed_users: list[str]) -> bool:
    folded = username.casefold()
    return any(folded == candidate.casefold() for candidate in allowed_users)


__all__ = [
    "GITHUB_AUTHORIZE_URL",
    "GITHUB_TOKEN_URL",
    "GITHUB_USER_URL",
    "GitHubIdpProvider",
    "HttpxIdpHttp",
    "IdpHttp",
    "IdpProvider",
    "OidcIdpProvider",
    "StaticIdpHttp",
    "build_idp_provider",
    "is_allowed_user",
]
