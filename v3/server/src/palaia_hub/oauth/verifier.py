"""The resource side: one JWT verifier per profile, beside the SPEC-108 tokens.

This module is the whole of SPEC-203 deliverable #4, and it is deliberately
almost empty of logic. Two rules produce that emptiness:

**1. The JWT validation is fastmcp's, not ours.** ``JWTVerifier`` already
checks the signature against the published public key, the ``exp``, the
``iss``, the ``aud`` and the required scopes, and it is the same class every
other fastmcp deployment exercises. Writing a second implementation of those
five checks in this repository would add a place for an ``aud``-confusion or
``alg``-confusion bug to hide, and it would not be reviewed by anyone outside
this project. So :func:`build_jwt_verifier` only *configures* it — with the
public key (not a JWKS URI: the key is in this process, so fetching it over
HTTP from ourselves would add a network dependency and a cache to reason
about for nothing), the issuer, and — the load-bearing argument — the one
canonical audience for that profile.

**2. Audience isolation is a constructor argument, not a runtime check.**
Each profile gets its own verifier pinned to its own ``aud``, so a token for
profile ``alpha`` presented to profile ``beta`` fails inside fastmcp's
audience comparison and comes back as the same 401 an expired or forged token
would. There is no code path here that could accidentally accept a token for
another resource, because there is no comparison here to get wrong.

**Both credentials keep working.** ``fastmcp.server.auth.MultiAuth`` tries
each verifier in order and takes the first that accepts, so a profile serves
OAuth access tokens *and* the SPEC-108 ``plt_`` tokens at the same time — an
existing setup does not break when the operator enables the OAuth server, and
a machine job can keep a simple bearer token if that is what suits it. The
:class:`palaia_hub.auth.verifier.PalaiaTokenVerifier` goes second: an OAuth
JWT is structurally distinguishable and far more common on a hub that has
OAuth on, so trying it first avoids paying an argon2 verify on the hot path.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastmcp.server.auth import AuthProvider, MultiAuth, TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl

from ..auth.store import TokenStore
from ..auth.verifier import PalaiaTokenVerifier
from .keys import ALGORITHM, SigningKey
from .resources import ResourceRegistry

logger = logging.getLogger("palaia_hub.oauth.verifier")


class ProfileAuth(MultiAuth):
    """``MultiAuth`` pinned to a profile's canonical resource URL.

    fastmcp derives the resource URL it advertises (in the 401's
    ``WWW-Authenticate: ... resource_metadata="..."`` pointer) by appending the
    mounted MCP path to ``resource_base_url``. Each profile's FastMCP app is
    mounted at ``"/"`` inside its own mount point (see
    :func:`palaia_hub.gateway.build.build_gateway`), so that derivation yields
    ``<audience>/`` — one trailing slash more than the ``resource`` value the
    protected-resource metadata document states, and therefore a pointer that
    does not round-trip cleanly.

    The canonical audience is this hub's to define
    (:class:`palaia_hub.oauth.resources.ResourceRegistry`), so this override
    stops the derivation from happening at all: whatever path the profile is
    mounted at, the advertised resource is exactly the audience its tokens
    carry. Nothing else about ``MultiAuth`` changes.
    """

    def _get_resource_url(self, path: str | None = None) -> AnyHttpUrl | None:
        """Ignore ``path``; the resource URL is the configured audience.

        Overrides ``AuthProvider._get_resource_url``, which is what fastmcp's
        HTTP app calls to build the ``resource_metadata`` pointer.
        """
        return super()._get_resource_url(None)


def build_jwt_verifier(
    key: SigningKey, resources: ResourceRegistry, profile: str
) -> JWTVerifier:
    """A ``JWTVerifier`` accepting only *this* profile's access tokens.

    Args:
        key: the signing key whose public half verifies tokens.
        resources: the registry that owns the canonical audience strings.
        profile: which profile's audience to pin to.
    """
    return JWTVerifier(
        public_key=key.public_pem(),
        algorithm=ALGORITHM,
        issuer=resources.issuer,
        audience=resources.audience(profile),
    )


def build_profile_auth(
    profiles: Mapping[str, object] | list[str] | tuple[str, ...],
    *,
    key: SigningKey | None = None,
    resources: ResourceRegistry | None = None,
    token_store: TokenStore | None = None,
) -> dict[str, AuthProvider]:
    """One :class:`AuthProvider` per profile path, combining every credential.

    Args:
        profiles: the profile paths to build verifiers for (any iterable of
            names; a mapping's keys are used, so a ``{profile: scopes}`` dict
            can be passed straight through).
        key: the OAuth signing key. Omit to build no JWT verifier — the
            SPEC-108-only posture, unchanged from before this SPEC.
        resources: the resource registry; required together with ``key``.
        token_store: the MVP token store. Omit to serve OAuth only.

    Returns:
        ``{profile path: AuthProvider}`` ready for
        :func:`palaia_hub.gateway.build.build_gateway`'s ``token_verifiers``.
        A profile with no credential at all is absent from the mapping rather
        than present with a verifier that accepts nothing — the gateway then
        mounts it unauthenticated, which the operating-mode policy
        (:func:`palaia_hub.auth.policy.check_gateway_auth_policy`) refuses in
        ``cloud``/``open``.
    """
    if (key is None) != (resources is None):
        raise ValueError("build_profile_auth needs `key` and `resources` together, or neither")

    providers: dict[str, AuthProvider] = {}
    for profile in list(profiles):
        verifiers: list[TokenVerifier] = []
        if key is not None and resources is not None:
            verifiers.append(build_jwt_verifier(key, resources, profile))
        if token_store is not None:
            verifiers.append(PalaiaTokenVerifier(token_store, profile))
        if not verifiers:
            continue
        # `resource_base_url` is what makes fastmcp's 401 carry
        # `WWW-Authenticate: Bearer resource_metadata="..."` — the pointer an
        # MCP client follows to discover this resource's authorization server
        # (RFC 9728 §5.1). Without it a client has nowhere to start.
        resource_base_url = (
            resources.audience(profile) if key is not None and resources is not None else None
        )
        providers[profile] = ProfileAuth(
            verifiers=verifiers,
            base_url=resources.issuer if resources is not None else None,
            resource_base_url=resource_base_url,
        )
    return providers


def summarize_profile_auth(providers: Mapping[str, AuthProvider]) -> list[str]:
    """One human-readable line per profile naming the credentials it accepts.

    SPEC-203 deliverable #6's "startup summary states which auth methods each
    profile serves". Returned rather than printed so a caller can log it, show
    it in the dashboard, or assert on it in a test.
    """
    lines: list[str] = []
    for profile in sorted(providers):
        provider = providers[profile]
        methods: list[str] = []
        sources = list(getattr(provider, "verifiers", [provider]))
        for source in sources:
            if isinstance(source, JWTVerifier):
                methods.append("oauth2 (access JWT)")
            elif isinstance(source, PalaiaTokenVerifier):
                methods.append("per-client token (plt_)")
            else:  # pragma: no cover - defensive: an auth type we did not wire
                methods.append(type(source).__name__)
        lines.append(f"profile {profile!r} accepts: {', '.join(methods) or 'nothing'}")
    return lines


def log_profile_auth(providers: Mapping[str, AuthProvider]) -> None:
    """Log :func:`summarize_profile_auth` at INFO, one line per profile."""
    for line in summarize_profile_auth(providers):
        logger.info("%s", line)


__all__ = [
    "ProfileAuth",
    "build_jwt_verifier",
    "build_profile_auth",
    "log_profile_auth",
    "summarize_profile_auth",
]
