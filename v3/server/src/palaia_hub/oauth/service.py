"""The authorization server itself: discovery, authorize, token, revoke, register.

One class, :class:`AuthorizationServer`, holds every protocol decision; the
HTTP layer (:mod:`palaia_hub.oauth.routes`) only parses requests, calls a
method here, and serializes the result. That split is deliberate — it keeps
the security-relevant logic testable without a transport and keeps the route
handlers too thin to hide a decision in.

Grants supported, and their fences:

* **Authorization code + PKCE (S256)** for interactive clients. PKCE is
  mandatory for *every* client, no exceptions and no ``plain``.
* **Refresh token**, with the grace-windowed rotation of
  :meth:`palaia_hub.oauth.store.OAuthStore.rotate_refresh_token`.
* **Client credentials** for machine identities only — and a machine identity
  can only exist because an operator provisioned it
  (:func:`palaia_hub.oauth.clients.provision_machine_client`). It is pinned to
  one audience, gets no refresh token, and its scope set cannot be widened by
  the request.

Two invariants worth stating once, because everything below depends on them:

1. **The ``aud`` claim is always composed by
   :class:`palaia_hub.oauth.resources.ResourceRegistry`**, never copied from
   the client's ``resource`` parameter (MASTERPLAN §5.5's resolved-audience
   lesson).
2. **Nothing here logs a credential.** Log lines name a ``client_id``, a
   profile, a grant id and an outcome; never a code, token, verifier, secret
   or password. The redaction filter is the net, not the plan.

**Known residual risk, stated rather than hidden.** SPEC-203's non-goals
exclude "consent screens beyond the single-owner login", so ``/authorize``
issues a code as soon as the owner has a live session, with no per-request
confirmation. The consequence is silent authorization: if the signed-in owner
is lured into loading a crafted ``/authorize`` URL naming an
attacker-controlled client and redirect URI, a code is minted and delivered to
that client, and — since the attacker chose the PKCE challenge — it can be
exchanged. What limits it today: the client must already be registerable (a
CIMD document the attacker controls, or a DCR registration), every issued
grant is visible in ``palaia-hub oauth clients`` and revocable, and access
tokens are audience-scoped and short-lived. What actually closes it is a
confirmation step on ``/authorize`` — one POST with the double-submit token
the sign-in form already uses — which belongs to the SPEC that owns consent
UX (SPEC-205's exposure work), not to this one. This paragraph exists so the
gap is a decision on the record rather than an oversight.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from ..auth.hashing import spend_constant_time_miss, verify_secret
from ..config import HubConfig, OAuthSettings, palaia_home
from . import pkce
from .cimd import CimdFetcher, match_redirect_uri
from .clients import register_dcr_client, resolve_client
from .errors import OAuthError
from .keys import ALGORITHM, SigningKey, now_seconds
from .login import LoginThrottle, verify_owner_password
from .models import ClientRow, IssuedTokens
from .resources import ResourceRegistry
from .secrets_util import new_secret
from .store import OAuthStore

logger = logging.getLogger("palaia_hub.oauth.service")

GRANT_AUTHORIZATION_CODE = "authorization_code"
GRANT_REFRESH_TOKEN = "refresh_token"
GRANT_CLIENT_CREDENTIALS = "client_credentials"

SUPPORTED_GRANT_TYPES = (
    GRANT_AUTHORIZATION_CODE,
    GRANT_REFRESH_TOKEN,
    GRANT_CLIENT_CREDENTIALS,
)

#: Path of the sign-in form ``/authorize`` sends an unauthenticated operator to.
LOGIN_PATH = "/oauth/login"
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"
REVOKE_PATH = "/oauth/revoke"
REGISTER_PATH = "/oauth/register"
JWKS_PATH = "/.well-known/jwks.json"


@dataclass(frozen=True, slots=True)
class AuthorizeRedirect:
    """Send the browser to ``location`` (a success *or* an error redirect)."""

    location: str


@dataclass(frozen=True, slots=True)
class LoginRequired:
    """No live session: show the sign-in form, then return to ``next_url``."""

    next_url: str


AuthorizeOutcome = AuthorizeRedirect | LoginRequired


class AuthorizationServer:
    """palaia as an OAuth 2.1 authorization server.

    Args:
        settings: the validated ``oauth:`` config block.
        profile_scopes: ``{gateway profile path: scopes grantable there}``.
            The keys define which resources exist; the values are the scope
            ceiling for a token minted for that resource.
        store: the state store, already opened.
        key: the signing key.
        cimd_fetcher: how client-id metadata documents are fetched. The
            default is the real SSRF-safe fetcher.
        throttle: failed-sign-in throttle (shared with the login routes).
        clock: seconds-resolution time source; injectable so the grace-window
            tests do not have to sleep.
    """

    def __init__(
        self,
        *,
        settings: OAuthSettings,
        profile_scopes: Mapping[str, Sequence[str]],
        store: OAuthStore,
        key: SigningKey,
        cimd_fetcher: CimdFetcher | None = None,
        throttle: LoginThrottle | None = None,
        clock: Callable[[], int] = now_seconds,
    ) -> None:
        if not settings.issuer:
            raise ValueError(
                "the OAuth server needs an issuer. Fix: set `oauth.issuer` in "
                "config.yaml to the public https URL clients reach this hub at."
            )
        self.settings = settings
        self.resources = ResourceRegistry(settings.issuer, list(profile_scopes))
        self._profile_scopes = {
            profile: tuple(dict.fromkeys(scopes)) for profile, scopes in profile_scopes.items()
        }
        self.store = store
        self.key = key
        self.cimd = cimd_fetcher or CimdFetcher()
        self.throttle = throttle or LoginThrottle()
        self._clock = clock

    # ------------------------------------------------------------ construction

    @classmethod
    def build(
        cls,
        config: HubConfig,
        profile_scopes: Mapping[str, Sequence[str]],
        *,
        home: Path | None = None,
        cimd_fetcher: CimdFetcher | None = None,
        clock: Callable[[], int] = now_seconds,
    ) -> AuthorizationServer:
        """Assemble a server from hub config: load/create the key, open the store."""
        resolved_home = Path(home) if home is not None else palaia_home()
        store = OAuthStore(resolved_home)
        store.open()
        key = SigningKey.load_or_create(resolved_home)
        return cls(
            settings=config.oauth,
            profile_scopes=profile_scopes,
            store=store,
            key=key,
            cimd_fetcher=cimd_fetcher,
            clock=clock,
        )

    @property
    def issuer(self) -> str:
        return self.resources.issuer

    def now(self) -> int:
        return self._clock()

    def scopes_for(self, audience: str) -> tuple[str, ...]:
        """The scope ceiling for ``audience`` (a canonical resource string)."""
        profile = self.resources.profile_for_audience(audience)
        if profile is None:  # pragma: no cover - audiences come from the registry
            return ()
        return self._profile_scopes.get(profile, ())

    # --------------------------------------------------------------- discovery

    def metadata(self) -> dict[str, object]:
        """RFC 8414 authorization-server metadata.

        ``client_id_metadata_document_supported`` is what tells an MCP
        2026-07-28 client it may skip registration entirely and present a CIMD
        URL as its ``client_id``; ``registration_endpoint`` stays advertised so
        older clients still have the (deprecated) DCR path.
        """
        issuer = self.issuer
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}{AUTHORIZE_PATH}",
            "token_endpoint": f"{issuer}{TOKEN_PATH}",
            "revocation_endpoint": f"{issuer}{REVOKE_PATH}",
            "registration_endpoint": f"{issuer}{REGISTER_PATH}",
            "jwks_uri": f"{issuer}{JWKS_PATH}",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": list(SUPPORTED_GRANT_TYPES),
            "code_challenge_methods_supported": [pkce.S256],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_basic",
                "client_secret_post",
            ],
            "revocation_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
            "id_token_signing_alg_values_supported": [ALGORITHM],
            "scopes_supported": sorted({s for v in self._profile_scopes.values() for s in v}),
            "client_id_metadata_document_supported": True,
            "authorization_response_iss_parameter_supported": True,
            "resource_indicators_supported": True,
        }

    def protected_resource_metadata(self, profile: str) -> dict[str, object]:
        """RFC 9728 protected-resource metadata for one MCP profile."""
        try:
            audience = self.resources.audience(profile)
        except KeyError as exc:
            raise OAuthError(
                "invalid_target", f"this hub serves no MCP profile named {profile!r}."
            ) from exc
        return {
            "resource": audience,
            "authorization_servers": [self.issuer],
            "scopes_supported": list(self._profile_scopes.get(profile, ())),
            "bearer_methods_supported": ["header"],
            "resource_name": f"palaia memory ({profile})",
        }

    def jwks(self) -> dict[str, object]:
        """The public signing key, as a JWKS document."""
        return dict(self.key.jwks())

    # --------------------------------------------------------------- authorize

    async def authorize(
        self, params: Mapping[str, str], *, session: str | None
    ) -> AuthorizeOutcome:
        """Handle an authorization request.

        Error handling follows RFC 6749 §4.1.2.1 exactly, and the distinction
        matters: until the ``client_id`` **and** the ``redirect_uri`` are both
        validated, an error must be shown to the user (raised as
        :class:`~palaia_hub.oauth.errors.OAuthError` and rendered as a page) —
        redirecting to an unvalidated URI would turn this endpoint into an open
        redirector. Once both are known good, every further error is delivered
        *to the client* as a redirect carrying ``error`` and ``state``.
        """
        now = self.now()

        # Authenticate the resource owner FIRST, before touching anything a
        # request parameter controls. This ordering is a security choice, not a
        # convenience: resolving a CIMD client_id makes an outbound HTTPS
        # request to a URL the caller chose, and doing that for an
        # unauthenticated caller would hand the internet an outbound-fetch
        # primitive on this host. The fetch is SSRF-hardened either way
        # (:mod:`palaia_hub.oauth.cimd`); not offering it to strangers is the
        # cheaper half of the defense. Every real client's user is signed in by
        # this point anyway, so nothing legitimate changes: an unauthenticated
        # authorization request lands on the sign-in form and re-runs
        # afterwards, which is what every authorization server does.
        username = self.current_user(session)
        if username is None:
            return LoginRequired(next_url=self._authorize_url(params))

        client_id = params.get("client_id", "").strip()
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required.")
        client = await resolve_client(
            self.store,
            self.cimd,
            client_id,
            now=now,
            allowed_scopes=sorted({s for v in self._profile_scopes.values() for s in v}),
        )
        redirect_uri = self._resolve_redirect_uri(client, params.get("redirect_uri"))

        # From here on, errors go back to the client (RFC 6749 §4.1.2.1).
        state = params.get("state")
        try:
            if params.get("response_type") != "code":
                raise OAuthError(
                    "unsupported_response_type",
                    "response_type must be 'code'; this server implements the "
                    "authorization code flow only (OAuth 2.1 removed the implicit "
                    "and password grants).",
                )
            if client.is_machine:
                raise OAuthError(
                    "unauthorized_client",
                    "a machine client cannot use the authorization code flow; it "
                    "uses grant_type=client_credentials.",
                )
            challenge = pkce.validate_challenge(
                params.get("code_challenge"), params.get("code_challenge_method")
            )
            audience = self.resources.resolve(params.get("resource"))
            scopes = self._resolve_scopes(params.get("scope"), audience)

            code = self.store.create_code(
                client_id=client.client_id,
                redirect_uri=redirect_uri,
                code_challenge=challenge,
                audience=audience,
                subject=username,
                scopes=scopes,
                now=now,
                ttl=self.settings.authorization_code_ttl,
            )
            logger.info(
                "issued an authorization code to client %s for %s",
                client.client_id,
                audience,
            )
            return AuthorizeRedirect(
                _with_query(
                    redirect_uri,
                    {"code": code, "state": state, "iss": self.issuer},
                )
            )
        except OAuthError as exc:
            logger.info(
                "authorization request from client %s failed: %s", client.client_id, exc.error
            )
            return AuthorizeRedirect(
                _with_query(
                    redirect_uri,
                    {
                        "error": exc.error,
                        "error_description": exc.description,
                        "state": state,
                        "iss": self.issuer,
                    },
                )
            )

    def _resolve_redirect_uri(self, client: ClientRow, presented: str | None) -> str:
        """Pick and validate the redirect URI, exact-matching a registered one."""
        if presented:
            return match_redirect_uri(client.redirect_uris, presented)
        if len(client.redirect_uris) == 1:
            return client.redirect_uris[0]
        raise OAuthError(
            "invalid_request",
            "redirect_uri is required because this client registered more than "
            "one.",
        )

    def _authorize_url(self, params: Mapping[str, str]) -> str:
        """Rebuild this authorization request as a relative URL, for the login hop."""
        return _with_query(AUTHORIZE_PATH, dict(params))

    def _resolve_scopes(self, requested: str | None, audience: str) -> tuple[str, ...]:
        """Intersect the requested scopes with what ``audience`` may grant.

        RFC 6749 §3.3 lets the server apply a default when the client sends no
        ``scope``, and the default here is the resource's full set. That is a
        conscious choice for a single-owner hub with no consent screen: the
        operator connected this client deliberately, there is no UI in this
        SPEC to refine the grant, and issuing a read-only token to a client
        that then cannot write is a worse failure than the alternative. A
        client that *does* send ``scope`` gets exactly what it asked for, and
        asking for something outside the ceiling is a loud ``invalid_scope``
        rather than a silent downgrade.
        """
        allowed = self.scopes_for(audience)
        if requested is None or not requested.strip():
            return allowed
        asked = tuple(dict.fromkeys(requested.split()))
        unknown = [scope for scope in asked if scope not in allowed]
        if unknown:
            raise OAuthError(
                "invalid_scope",
                "the requested scope is not available for this resource "
                f"(it grants: {' '.join(allowed) or '<none>'}).",
            )
        return asked

    # ------------------------------------------------------------------- login

    def sign_in(self, username: str, password: str) -> tuple[str, int]:
        """Verify the owner's password and open a session. Returns (id, expiry)."""
        now = self.now()
        verified = verify_owner_password(
            self.store, username, password, throttle=self.throttle
        )
        session, expires_at = self.store.create_login_session(
            verified, now=now, ttl=self.settings.session_ttl
        )
        logger.info("owner %r signed in", verified)
        return session, expires_at

    def sign_out(self, session: str | None) -> None:
        if session:
            self.store.delete_login_session(session)

    def current_user(self, session: str | None) -> str | None:
        if not session:
            return None
        return self.store.get_login_session(session, self.now())

    # ------------------------------------------------------------------- token

    def token(
        self,
        form: Mapping[str, str],
        *,
        basic_auth: tuple[str, str] | None = None,
    ) -> IssuedTokens:
        """Handle a token request for any supported grant type.

        Synchronous on purpose: every step is a SQLite statement or an argon2
        verify, both blocking and both fast. :mod:`palaia_hub.oauth.routes`
        calls it through ``asyncio.to_thread``, which means the six
        simultaneous refreshes of a fanned-out connector really do run on six
        threads and really do contend for
        :class:`~palaia_hub.oauth.store.OAuthStore`'s lock — the property the
        concurrency test needs in order to prove anything.
        """
        grant_type = form.get("grant_type", "")
        if grant_type not in SUPPORTED_GRANT_TYPES:
            raise OAuthError(
                "unsupported_grant_type",
                f"grant_type must be one of {list(SUPPORTED_GRANT_TYPES)}.",
            )
        # Opportunistic, throttled registered-client GC. Here rather than in a
        # background task because the token endpoint is the one place that is
        # guaranteed to be exercised on a live hub, and a GC that only runs
        # when someone remembers to trigger it is the disease, not the cure.
        self._maybe_prune_clients()

        if grant_type == GRANT_AUTHORIZATION_CODE:
            return self._authorization_code(form)
        if grant_type == GRANT_REFRESH_TOKEN:
            return self._refresh(form)
        return self._client_credentials(form, basic_auth)

    def _authorization_code(self, form: Mapping[str, str]) -> IssuedTokens:
        now = self.now()
        code = form.get("code")
        if not code:
            raise OAuthError("invalid_request", "code is required.")
        client_id = form.get("client_id", "").strip()
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required.")

        code_row, grant = self.store.exchange_code(code, now)
        # Bind the code to the client and redirect_uri it was issued for. Both
        # checks are OAuth 2.1 §4.1.3 requirements; without the first, one
        # client could redeem another's code.
        if code_row.client_id != client_id:
            self.store.revoke_grant(grant.grant_id, now)
            logger.warning(
                "client %s tried to redeem a code issued to %s; revoked the grant",
                client_id,
                code_row.client_id,
            )
            raise OAuthError("invalid_grant", "the authorization code is not valid.")
        presented_redirect = form.get("redirect_uri")
        if presented_redirect is not None and presented_redirect != code_row.redirect_uri:
            self.store.revoke_grant(grant.grant_id, now)
            raise OAuthError("invalid_grant", "the authorization code is not valid.")

        try:
            pkce.verify_verifier(form.get("code_verifier"), code_row.code_challenge)
        except OAuthError:
            # A failed PKCE check on a code that was just spent means the code
            # leaked to someone without the verifier — the grant it created is
            # worthless to the legitimate client anyway.
            self.store.revoke_grant(grant.grant_id, now)
            raise

        refresh_token, _expiry = self.store.issue_refresh_token(
            grant=grant, now=now, ttl=self.settings.refresh_token_ttl
        )
        access_token = self._mint_access_token(
            subject=grant.subject,
            client_id=grant.client_id,
            audience=grant.audience,
            scopes=grant.scopes,
            now=now,
        )
        logger.info(
            "issued tokens to client %s for %s (grant %s)",
            grant.client_id,
            grant.audience,
            grant.grant_id[:8],
        )
        return IssuedTokens(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl,
            scopes=grant.scopes,
            audience=grant.audience,
            refresh_token=refresh_token,
        )

    def _refresh(self, form: Mapping[str, str]) -> IssuedTokens:
        now = self.now()
        presented = form.get("refresh_token")
        if not presented:
            raise OAuthError("invalid_request", "refresh_token is required.")
        outcome = self.store.rotate_refresh_token(
            presented,
            now=now,
            ttl=self.settings.refresh_token_ttl,
            grace_window=self.settings.refresh_grace_window,
        )
        grant = outcome.grant
        client_id = form.get("client_id")
        if client_id and client_id != grant.client_id:
            raise OAuthError("invalid_grant", "the refresh token is not valid.")
        # A refresh may narrow the grant (RFC 6749 §6) but never widen it.
        scopes = self._narrow_scopes(form.get("scope"), grant.scopes)
        access_token = self._mint_access_token(
            subject=grant.subject,
            client_id=grant.client_id,
            audience=grant.audience,
            scopes=scopes,
            now=now,
        )
        logger.info(
            "refreshed tokens for client %s (grant %s%s)",
            grant.client_id,
            grant.grant_id[:8],
            ", replay inside grace window" if outcome.replayed else "",
        )
        return IssuedTokens(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl,
            scopes=scopes,
            audience=grant.audience,
            refresh_token=outcome.refresh_token,
        )

    def _client_credentials(
        self, form: Mapping[str, str], basic_auth: tuple[str, str] | None
    ) -> IssuedTokens:
        """The machine-identity grant: pinned audience, no refresh token."""
        now = self.now()
        if basic_auth is not None:
            client_id, client_secret = basic_auth
        else:
            client_id = form.get("client_id", "").strip()
            client_secret = form.get("client_secret", "")
        unauthorized = OAuthError(
            "invalid_client",
            "client authentication failed.",
            headers={"WWW-Authenticate": 'Basic realm="palaia"'},
        )
        if not client_id or not client_secret:
            raise unauthorized
        client = self.store.get_client(client_id)
        if client is None or not client.is_machine or client.client_secret_hash is None:
            # Same cost and same answer whether the client is unknown, public,
            # or a machine client with a wrong secret.
            spend_constant_time_miss()
            raise unauthorized
        if not verify_secret(client_secret, client.client_secret_hash):
            logger.warning("client_credentials authentication failed for %s", client_id)
            raise unauthorized
        if GRANT_CLIENT_CREDENTIALS not in client.grant_types:
            raise OAuthError(
                "unauthorized_client",
                "this client is not allowed to use the client_credentials grant.",
            )
        if client.pinned_audience is None:  # pragma: no cover - set at provisioning
            raise OAuthError(
                "invalid_target", "this machine client has no audience pinned to it."
            )
        # The audience is the pinned one, full stop. A `resource` parameter is
        # honored only insofar as it must *agree* with the pin — a machine
        # identity can never be talked into a token for another resource.
        requested = form.get("resource")
        if requested:
            resolved = self.resources.resolve(requested)
            if resolved != client.pinned_audience:
                raise OAuthError(
                    "invalid_target",
                    "this machine client is pinned to a different resource.",
                )
        scopes = self._narrow_scopes(form.get("scope"), client.scopes)
        self.store.touch_client(client.client_id, now)
        access_token = self._mint_access_token(
            subject=f"machine:{client.client_id}",
            client_id=client.client_id,
            audience=client.pinned_audience,
            scopes=scopes,
            now=now,
        )
        logger.info(
            "issued a machine access token to %s for %s",
            client.client_id,
            client.pinned_audience,
        )
        # No refresh token, by design (MASTERPLAN §5.5): a job re-authenticates
        # with its secret whenever it needs a token, so there is no long-lived
        # bearer credential to steal beyond the secret the operator can rotate.
        return IssuedTokens(
            access_token=access_token,
            expires_in=self.settings.access_token_ttl,
            scopes=scopes,
            audience=client.pinned_audience,
        )

    def _narrow_scopes(
        self, requested: str | None, granted: Sequence[str]
    ) -> tuple[str, ...]:
        if requested is None or not requested.strip():
            return tuple(granted)
        asked = tuple(dict.fromkeys(requested.split()))
        extra = [scope for scope in asked if scope not in granted]
        if extra:
            raise OAuthError(
                "invalid_scope",
                "a token request may narrow the granted scope but never widen it.",
            )
        return asked

    def _mint_access_token(
        self,
        *,
        subject: str,
        client_id: str,
        audience: str,
        scopes: Sequence[str],
        now: int,
    ) -> str:
        """Sign one short-lived access token.

        The claim set is deliberately minimal: ``iss``/``aud``/``exp`` are what
        the resource side checks, ``scope`` is what the per-tool enforcement
        reads (:func:`palaia_hub.auth.enforcement.missing_scope_error`),
        ``client_id`` and ``sub`` are for attribution, and ``jti`` gives an
        operator something to correlate in logs. No vault content, no user
        data, nothing that would matter if a token were read: a JWT is
        base64, not encryption.
        """
        claims: dict[str, object] = {
            "iss": self.issuer,
            "sub": subject,
            "aud": audience,
            "client_id": client_id,
            "scope": " ".join(scopes),
            "iat": now,
            "nbf": now,
            "exp": now + self.settings.access_token_ttl,
            "jti": new_secret(),
        }
        return self.key.sign(claims)

    # ------------------------------------------------------------------ revoke

    def revoke(self, form: Mapping[str, str]) -> None:
        """RFC 7009 revocation. Always succeeds from the client's point of view.

        RFC 7009 §2.2 requires a 200 even for an unknown token: telling a
        caller "that token did not exist" is a lookup oracle, and a client
        cleaning up cannot act on the difference anyway.
        """
        token = form.get("token")
        if not token:
            raise OAuthError("invalid_request", "token is required.")
        if self.store.revoke_refresh_token(token, self.now()):
            logger.info("revoked a refresh token and its grant")

    # ---------------------------------------------------------------- register

    def register(self, body: object) -> ClientRow:
        """RFC 7591 dynamic client registration (the deprecated fallback)."""
        self._maybe_prune_clients()
        return register_dcr_client(
            self.store,
            body,
            now=self.now(),
            allowed_scopes=sorted({s for v in self._profile_scopes.values() for s in v}),
        )

    # ---------------------------------------------------------------------- gc

    def _maybe_prune_clients(self) -> None:
        self.store.prune_clients(
            now=self.now(),
            ttl_seconds=self.settings.client_gc_ttl,
            throttle_seconds=self.settings.client_gc_interval,
        )


def _with_query(url: str, params: Mapping[str, str | None]) -> str:
    """Append ``params`` (skipping ``None`` values) to ``url``'s query string."""
    parts = urlsplit(url)
    existing = parts.query
    added = urlencode({k: v for k, v in params.items() if v is not None})
    query = f"{existing}&{added}" if existing and added else (existing or added)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


__all__ = [
    "AUTHORIZE_PATH",
    "GRANT_AUTHORIZATION_CODE",
    "GRANT_CLIENT_CREDENTIALS",
    "GRANT_REFRESH_TOKEN",
    "JWKS_PATH",
    "LOGIN_PATH",
    "REGISTER_PATH",
    "REVOKE_PATH",
    "SUPPORTED_GRANT_TYPES",
    "TOKEN_PATH",
    "AuthorizationServer",
    "AuthorizeOutcome",
    "AuthorizeRedirect",
    "LoginRequired",
]
