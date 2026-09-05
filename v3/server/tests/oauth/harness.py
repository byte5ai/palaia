"""A whole hub with the OAuth server on, assembled for one test.

Everything the SPEC-203 tests need in one place: a gateway with two profiles
(so audience isolation is testable), the authorization server mounted on the
same ASGI app, the SPEC-108 token store alongside it, and a controllable
clock so the refresh grace window can be crossed without sleeping.

The app is driven through ``httpx.ASGITransport``, exactly like the SPEC-108
HTTP tests (``tests/auth/_asgi_mcp_client.py``): no socket, no subprocess, but
the real middleware stack — the real 401s, the real ``WWW-Authenticate``, and
the real ``fastmcp`` auth path a connector would hit.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import FastAPI

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.events import EventBus
from palaia_hub.gateway.build import GatewayASGI, build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.oauth import (
    AuthorizationServer,
    IdpHttp,
    OAuthStore,
    ResourceRegistry,
    SigningKey,
    StaticCimdFetcher,
    build_profile_auth,
    oauth_client_connected_hook,
    set_owner_password,
)

#: The issuer is also the host the ASGI test client talks to, so discovery
#: URLs the hub advertises can be followed verbatim — and so the ``Secure``
#: cookies the login flow sets (the issuer is https) are actually sent back.
ISSUER = "https://testserver"
OWNER_USERNAME = "owner"
OWNER_PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
VAULT_KEY = "work"
PROFILES = ("alpha", "beta")

READ_SCOPE = f"vault:{VAULT_KEY}:read"
WRITE_SCOPE = f"vault:{VAULT_KEY}:write"
ALL_SCOPES = (READ_SCOPE, WRITE_SCOPE)

#: A CIMD client, and the metadata document its client_id resolves to.
CIMD_CLIENT_ID = "https://client.test/mcp-client.json"
CIMD_REDIRECT_URI = "https://client.test/callback"
CIMD_DOCUMENT = {
    "client_id": CIMD_CLIENT_ID,
    "client_name": "Test connector",
    "redirect_uris": [CIMD_REDIRECT_URI],
    "grant_types": ["authorization_code", "refresh_token"],
    "token_endpoint_auth_method": "none",
}


class Clock:
    """A hand-cranked clock, so grace windows are crossed without sleeping."""

    def __init__(self, start: int = 1_800_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += seconds


@dataclass
class Harness:
    """Everything one test needs, already wired together."""

    app: FastAPI
    gateway: GatewayASGI
    server: AuthorizationServer
    store: OAuthStore
    key: SigningKey
    resources: ResourceRegistry
    token_store: TokenStore
    clock: Clock
    cimd: StaticCimdFetcher
    home: Path
    #: The bus `create_app` publishes onto — also what
    #: `oauth_client_connected_hook` (issue #272) is wired to below, so a
    #: test can assert on `client.connected` the same way it would in
    #: production. Same object `app.state.event_bus` holds.
    event_bus: EventBus
    profiles: tuple[str, ...] = field(default=PROFILES)

    def audience(self, profile: str) -> str:
        return self.resources.audience(profile)


def build_harness(
    home: Path,
    *,
    profiles: tuple[str, ...] = PROFILES,
    mode: str = "cloud",
    settings: OAuthSettings | None = None,
    with_owner: bool = True,
    with_plt_tokens: bool = True,
    idp_http: IdpHttp | None = None,
) -> Harness:
    """Assemble the app, the authorization server, and the resource side."""
    clock = Clock()
    oauth_settings = settings or OAuthSettings(enabled=True, issuer=ISSUER, profiles=list(profiles))
    config = HubConfig(mode=mode, host="127.0.0.1", oauth=oauth_settings)  # type: ignore[arg-type]

    store = OAuthStore(home)
    store.open()
    key = SigningKey.load_or_create(home)
    cimd = StaticCimdFetcher({CIMD_CLIENT_ID: dict(CIMD_DOCUMENT)})
    profile_scopes = {profile: list(ALL_SCOPES) for profile in profiles}
    server = AuthorizationServer(
        settings=oauth_settings,
        profile_scopes=profile_scopes,
        store=store,
        key=key,
        cimd_fetcher=cimd,
        clock=clock,
        idp_http=idp_http,
    )
    if with_owner and oauth_settings.idp is None:
        set_owner_password(store, OWNER_USERNAME, OWNER_PASSWORD, now=clock())

    token_store = TokenStore(home=home)
    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key=VAULT_KEY, name=VAULT_KEY, purpose="Work vault.")],
        profiles=[ProfileConfig(path=profile, vaults=[VAULT_KEY]) for profile in profiles],
    )
    # Built here (not left for `create_app` to build its own) so
    # `oauth_client_connected_hook` (issue #272) and `create_app` publish
    # onto the same bus a test can assert against.
    event_bus = EventBus()
    providers = build_profile_auth(
        profiles,
        key=key,
        resources=server.resources,
        token_store=token_store if with_plt_tokens else None,
        on_oauth_verified=oauth_client_connected_hook(event_bus),
    )
    gateway = build_gateway(
        gateway_config,
        {VAULT_KEY: FakeVaultService()},
        token_verifiers=providers,  # type: ignore[arg-type]
    )
    app = create_app(
        config,
        gateway=gateway,
        oauth_server=server,
        token_store=token_store,
        event_bus=event_bus,
    )
    return Harness(
        app=app,
        gateway=gateway,
        server=server,
        store=store,
        key=key,
        resources=server.resources,
        token_store=token_store,
        clock=clock,
        cimd=cimd,
        home=home,
        event_bus=event_bus,
        profiles=profiles,
    )


# ------------------------------------------------------- consent (issue #328)

_HIDDEN_INPUT_RE = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)">')


def is_consent_page(response: httpx.Response) -> bool:
    """Is ``response`` the consent page ``GET /oauth/authorize`` renders?"""
    return response.status_code == 200 and 'name="decision"' in response.text


async def approve_consent(
    http: httpx.AsyncClient, page: httpx.Response, *, decision: str = "allow"
) -> httpx.Response:
    """Answer the consent page the way a browser would: echo its hidden fields
    and the session's CSRF cookie in one POST. Returns the POST response (a 303
    to the client's redirect URI on success)."""
    assert is_consent_page(page), (page.status_code, page.text[:300])
    fields = {
        html.unescape(name): html.unescape(value)
        for name, value in _HIDDEN_INPUT_RE.findall(page.text)
    }
    fields["csrf_token"] = http.cookies["palaia_oauth_csrf"]
    fields["decision"] = decision
    return await http.post("/oauth/authorize", data=fields)


async def authorize_with_consent(
    http: httpx.AsyncClient, path: str, *, params: dict[str, str]
) -> httpx.Response:
    """``GET /oauth/authorize`` and, when the owner is signed in, approve the
    consent page — one call for the tests that only care about the code. A
    response that is not the consent page (the sign-in hop, an error page)
    is returned as is for the caller to assert on."""
    page = await http.get(path, params=params)
    if not is_consent_page(page):
        return page
    return await approve_consent(http, page)
