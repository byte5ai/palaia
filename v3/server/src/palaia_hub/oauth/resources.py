"""Resource indicators (RFC 8707) resolved to *our* canonical audiences.

This module exists because of one production failure recorded in MASTERPLAN
§5.5: **"resource indicators are resolved against the configured canonical
audience, never minted verbatim — clients disagree about trailing path
segments, and a verbatim ``aud`` produces tokens that verify at the AS and
fail silently at the resource."** A client that asks for
``https://hub/work/mcp`` and one that asks for ``https://hub/work`` mean the
same protected resource; if the ``aud`` claim is copied from whatever the
client sent, exactly one of them gets a token the resource server rejects,
and the failure surfaces as an unexplained 401 on the *next* call rather
than as an error on the token request.

So: a resource indicator is **matched** against the profiles this hub
actually serves, and the ``aud`` claim is always
:meth:`ResourceRegistry.audience` — a string this module composed, never a
string a client supplied. An indicator that does not match a known profile
is an ``invalid_target`` error at the token endpoint (loud, immediate,
actionable), never a token nobody can use.

Canonical audience shape (SPEC-203 acceptance criterion "resource indicator
``<issuer>/<name>/mcp`` resolves to ``<issuer>/<name>``"):

    audience(profile) == f"{issuer}/{profile}"

and these all resolve to it, for a profile named ``work``:

    <issuer>/work            <issuer>/work/
    <issuer>/work/mcp        <issuer>/work/mcp/
    <issuer>/mcp/work        <issuer>/mcp/work/
    <issuer>/mcp/work/mcp

The ``/mcp/<profile>`` forms are accepted because that is the actual URL
path the gateway mounts a profile at (``/mcp/<profile>`` — see
:func:`palaia_hub.gateway.build.build_gateway`), so a client that derives
its resource indicator from the endpoint URL it is talking to lands there.
Nothing outside the issuer's own origin (and base path, if the issuer has
one) is ever accepted.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlsplit

from .errors import OAuthError

#: A path segment that is a routing artifact rather than a resource name.
#: Tolerated on either side of the profile segment (see the module docstring)
#: because clients disagree about whether it belongs in the indicator.
_MCP_SEGMENT = "mcp"


def normalize_issuer(issuer: str) -> str:
    """Return ``issuer`` in the exact form every metadata document repeats.

    Lowercases the scheme and host (they are case-insensitive per RFC 3986
    §3.1/§3.2.2 but the ``iss`` claim is compared literally), and strips
    trailing slashes so ``https://hub/`` and ``https://hub`` cannot produce
    two different issuer strings for the same deployment.

    Raises:
        ValueError: the issuer is not an absolute ``http``/``https`` URL, or
            carries a query or fragment. RFC 8414 §2 requires an issuer with
            neither.
    """
    parts = urlsplit(issuer.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(
            f"oauth issuer {issuer!r} must be an absolute http(s) URL, e.g. "
            f"'https://hub.example.com'. Fix: set `oauth.issuer` in config.yaml."
        )
    if parts.query or parts.fragment:
        raise ValueError(
            f"oauth issuer {issuer!r} must not carry a query or fragment "
            f"(RFC 8414 §2). Fix: set `oauth.issuer` to just the origin (plus a "
            f"base path if the hub is reverse-proxied under one)."
        )
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


class ResourceRegistry:
    """The profiles this authorization server issues audience-scoped tokens for.

    Args:
        issuer: the AS issuer identifier; normalized via
            :func:`normalize_issuer`.
        profiles: gateway profile paths (the ``path`` of each
            :class:`palaia_hub.gateway.config.ProfileConfig`).
    """

    def __init__(self, issuer: str, profiles: Sequence[str]) -> None:
        self.issuer = normalize_issuer(issuer)
        self._profiles = tuple(dict.fromkeys(profiles))
        parts = urlsplit(self.issuer)
        self._origin = f"{parts.scheme}://{parts.netloc}"
        # Segments of the issuer's own base path, if it has one (a hub
        # reverse-proxied at https://example.com/palaia). Stripped off a
        # resource indicator before the profile is looked at.
        self._base_segments = tuple(s for s in parts.path.split("/") if s)

    @property
    def profiles(self) -> tuple[str, ...]:
        """Profile paths, in registration order, de-duplicated."""
        return self._profiles

    def audience(self, profile: str) -> str:
        """The canonical ``aud`` claim for ``profile``.

        Raises:
            KeyError: ``profile`` is not served by this hub.
        """
        if profile not in self._profiles:
            raise KeyError(f"no MCP profile {profile!r} on this hub")
        return f"{self.issuer}/{profile}"

    def audiences(self) -> dict[str, str]:
        """``{profile: canonical audience}`` for every served profile."""
        return {profile: self.audience(profile) for profile in self._profiles}

    def profile_for_audience(self, audience: str) -> str | None:
        """Reverse of :meth:`audience`; ``None`` if nothing matches."""
        for profile in self._profiles:
            if self.audience(profile) == audience:
                return profile
        return None

    def metadata_url(self, profile: str) -> str:
        """This profile's RFC 9728 protected-resource-metadata URL.

        RFC 9728 §3.1 inserts ``/.well-known/oauth-protected-resource``
        between the origin and the resource's path, so the canonical
        audience ``<issuer>/<profile>`` is described at
        ``<origin>/.well-known/oauth-protected-resource[/<base>]/<profile>``.
        """
        if profile not in self._profiles:
            raise KeyError(f"no MCP profile {profile!r} on this hub")
        suffix = "/".join((*self._base_segments, profile))
        return f"{self._origin}/.well-known/oauth-protected-resource/{suffix}"

    # ------------------------------------------------------------- resolution

    def resolve(self, resource: str | None) -> str:
        """Resolve a client's ``resource`` parameter to a canonical audience.

        Args:
            resource: the RFC 8707 ``resource`` parameter, or ``None`` when
                the client sent none.

        Returns:
            The canonical audience string — always one this registry
            composed, never the client's input (see the module docstring).

        Raises:
            OAuthError: ``invalid_target`` when the indicator names no
                profile this hub serves, or when the client omitted it and
                the hub serves more than one profile (guessing which one
                they meant is exactly the failure mode this module exists to
                prevent).
        """
        if not self._profiles:
            raise OAuthError(
                "invalid_target",
                "this hub serves no MCP profiles, so no access token can be "
                "audience-scoped to one. Fix: mount at least one gateway profile.",
            )
        if resource is None or not resource.strip():
            if len(self._profiles) == 1:
                return self.audience(self._profiles[0])
            raise OAuthError(
                "invalid_target",
                "a 'resource' parameter is required because this hub serves "
                f"several MCP profiles ({', '.join(self._profiles)}). Fix: send "
                "the resource indicator from the profile's protected-resource "
                "metadata document (RFC 8707).",
            )
        profile = self._match(resource.strip())
        if profile is None:
            raise OAuthError(
                "invalid_target",
                "the requested 'resource' does not identify an MCP profile on "
                f"this hub (it serves: {', '.join(self._profiles)}). Fix: use the "
                "'resource' value from the profile's protected-resource metadata "
                "document.",
            )
        return self.audience(profile)

    def _match(self, resource: str) -> str | None:
        """The profile ``resource`` identifies, or ``None``.

        Deliberately total and boring: parse, compare the origin, strip the
        issuer's base path, tolerate one ``mcp`` segment on either side, and
        require exactly one segment left that names a known profile. Anything
        else — a longer path, a query, a fragment, a different host — is not
        a match, so it becomes ``invalid_target`` upstream.
        """
        parts = urlsplit(resource)
        if parts.fragment:
            # RFC 8707 §2: a resource indicator MUST NOT include a fragment.
            return None
        if parts.query:
            return None
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            return None
        if f"{parts.scheme.lower()}://{parts.netloc.lower()}" != self._origin:
            return None

        segments = [s for s in parts.path.split("/") if s]
        base = list(self._base_segments)
        if segments[: len(base)] != base:
            return None
        segments = segments[len(base) :]

        # Tolerate the routing segment on either side: '<profile>/mcp' and
        # 'mcp/<profile>' (and both at once) all name the same resource.
        if segments and segments[-1] == _MCP_SEGMENT:
            segments = segments[:-1]
        if len(segments) == 2 and segments[0] == _MCP_SEGMENT:
            segments = segments[1:]
        if len(segments) != 1:
            return None
        return segments[0] if segments[0] in self._profiles else None


__all__ = ["ResourceRegistry", "normalize_issuer"]
