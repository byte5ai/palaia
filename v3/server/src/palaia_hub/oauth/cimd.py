"""OAuth Client ID Metadata Documents — the registration path MCP recommends.

Facts this module is built on (``v3/research/mcp-landscape-2026.md`` §1):
MCP 2025-11-25 introduced **CIMD** as the recommended client registration
mechanism, and MCP 2026-07-28 **deprecated RFC 7591 Dynamic Client
Registration** in its favour. A CIMD client's ``client_id`` *is* an https URL
that resolves to a JSON metadata document describing the client; there is no
registration request, so there is no registration table to fill up with a
fresh row on every reconnect (which is the disease
:meth:`palaia_hub.oauth.store.OAuthStore.prune_clients` treats on the DCR
side).

**The whole security surface here is one outbound fetch of a URL an
unauthenticated caller chose**, so it is server-side request forgery bait.
The fetch therefore goes through fastmcp's own
:func:`fastmcp.server.auth.ssrf.ssrf_safe_fetch` rather than a plain
``httpx.get``: HTTPS only, DNS resolved and the resulting IP validated
against private/loopback/link-local/CGNAT ranges, the connection made to
that pinned IP (so a rebind between check and connect cannot redirect it),
redirects disabled, response size capped, overall timeout enforced. That is
the same hardened path fastmcp uses for untrusted JWKS URIs; reusing it
beats writing a second one here.

**Validation is strict and closed.** A document is accepted only if it is a
JSON object whose ``client_id`` equals the URL it was fetched from
exactly — otherwise a document could claim someone else's identity — and
whose redirect URIs, grant types and auth method all pass the checks below.
Unknown members are ignored rather than rejected (the document format is
allowed to grow), but nothing unknown is ever *used*.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from fastmcp.server.auth.ssrf import SSRFError, SSRFFetchError, ssrf_safe_fetch

from .errors import OAuthError

logger = logging.getLogger("palaia_hub.oauth.cimd")

#: Cap on the metadata document body. A client description is a few hundred
#: bytes; anything larger is either a mistake or an attempt to make the hub
#: chew through a large response.
MAX_DOCUMENT_BYTES = 16384

FETCH_TIMEOUT_SECONDS = 10.0
OVERALL_TIMEOUT_SECONDS = 20.0

#: The grant types an interactive client may declare. ``client_credentials``
#: is deliberately absent: machine identities are admin-provisioned only
#: (MASTERPLAN §5.5), and a self-registering client must never be able to
#: talk itself into one.
ALLOWED_GRANT_TYPES = ("authorization_code", "refresh_token")

MAX_REDIRECT_URIS = 10
MAX_CLIENT_NAME_CHARS = 200


def is_cimd_client_id(client_id: str) -> bool:
    """Is ``client_id`` shaped like a Client ID Metadata Document URL?

    Only ``https`` counts. An http URL would make the document — and
    therefore the client's declared redirect URIs — trivially forgeable in
    transit, and ``ssrf_safe_fetch`` refuses it anyway.
    """
    parts = urlsplit(client_id)
    return parts.scheme == "https" and bool(parts.netloc) and not parts.fragment


def validate_redirect_uri(uri: str) -> str:
    """Validate one redirect URI, returning it unchanged.

    Accepts https anywhere, and http **only** on a loopback host — the
    native/CLI client case OAuth 2.1 §10.3.3 explicitly allows (a desktop
    client listening on ``http://127.0.0.1:<port>/callback``). Anything else,
    including a fragment (RFC 6749 §3.1.2 forbids one) or a non-loopback
    http URL, is rejected.
    """
    parts = urlsplit(uri)
    if parts.fragment:
        raise OAuthError(
            "invalid_redirect_uri",
            "a redirect_uri must not contain a fragment (RFC 6749 §3.1.2).",
        )
    if not parts.netloc:
        raise OAuthError("invalid_redirect_uri", "a redirect_uri must be an absolute URL.")
    if parts.scheme == "https":
        return uri
    if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "::1", "localhost"):
        return uri
    raise OAuthError(
        "invalid_redirect_uri",
        "a redirect_uri must use https, or http on a loopback host for a native "
        "client (OAuth 2.1 §10.3.3).",
    )


def validate_metadata(document: Any, *, expected_client_id: str) -> dict[str, Any]:
    """Validate a parsed CIMD document against ``expected_client_id``.

    Returns a normalized dict with exactly the members this hub uses:
    ``client_id``, ``client_name``, ``redirect_uris``, ``grant_types``.

    Raises:
        OAuthError: ``invalid_client_metadata`` (or ``invalid_redirect_uri``)
            for anything malformed.
    """
    if not isinstance(document, dict):
        raise OAuthError(
            "invalid_client_metadata",
            "the client-id metadata document must be a JSON object.",
        )
    declared = document.get("client_id")
    if declared != expected_client_id:
        # A document that names a different client_id is either misconfigured
        # or trying to be issued tokens under someone else's identity.
        raise OAuthError(
            "invalid_client_metadata",
            "the metadata document's 'client_id' must equal the URL it was "
            "fetched from.",
        )
    redirect_uris = document.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise OAuthError(
            "invalid_client_metadata",
            "the metadata document must list at least one 'redirect_uris' entry.",
        )
    if len(redirect_uris) > MAX_REDIRECT_URIS:
        raise OAuthError(
            "invalid_client_metadata",
            f"a client may declare at most {MAX_REDIRECT_URIS} redirect URIs.",
        )
    validated = [validate_redirect_uri(_as_str(uri, "redirect_uris")) for uri in redirect_uris]

    grant_types = document.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list):
        raise OAuthError("invalid_client_metadata", "'grant_types' must be a list.")
    unsupported = [g for g in grant_types if g not in ALLOWED_GRANT_TYPES]
    if unsupported:
        raise OAuthError(
            "invalid_client_metadata",
            "a self-registering client may only declare the "
            f"{list(ALLOWED_GRANT_TYPES)} grant types; machine-to-machine "
            "credentials are provisioned by the hub's operator, never requested.",
        )

    auth_method = document.get("token_endpoint_auth_method", "none")
    if auth_method != "none":
        raise OAuthError(
            "invalid_client_metadata",
            "a client registered through a metadata document is a public client: "
            "'token_endpoint_auth_method' must be 'none' (it authenticates with "
            "PKCE, not a secret).",
        )

    name = document.get("client_name") or expected_client_id
    client_name = _as_str(name, "client_name")[:MAX_CLIENT_NAME_CHARS]

    return {
        "client_id": expected_client_id,
        "client_name": client_name,
        "redirect_uris": validated,
        "grant_types": list(dict.fromkeys(grant_types)),
    }


def _as_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OAuthError(
            "invalid_client_metadata", f"'{field}' must contain non-empty strings."
        )
    return value


class CimdFetcher:
    """Fetches and validates Client ID Metadata Documents, SSRF-safely.

    A separate object (rather than a module function) purely so tests and
    offline deployments can substitute one — see
    :class:`StaticCimdFetcher`. The production implementation has no
    configuration to get wrong.
    """

    async def fetch(self, client_id: str) -> dict[str, Any]:
        """Fetch and validate the document at ``client_id``.

        Raises:
            OAuthError: ``invalid_client_metadata`` when the URL cannot be
                fetched safely, is not JSON, or fails validation. The
                description never echoes the response body — a client could
                otherwise use the hub as a reflector for arbitrary content.
        """
        if not is_cimd_client_id(client_id):
            raise OAuthError(
                "invalid_client_metadata",
                "a client-id metadata document URL must be https with no fragment.",
            )
        try:
            body = await ssrf_safe_fetch(
                client_id,
                max_size=MAX_DOCUMENT_BYTES,
                timeout=FETCH_TIMEOUT_SECONDS,
                overall_timeout=OVERALL_TIMEOUT_SECONDS,
            )
        except (SSRFError, SSRFFetchError) as exc:
            logger.info("refused to fetch client-id metadata document: %s", type(exc).__name__)
            raise OAuthError(
                "invalid_client_metadata",
                "the client-id metadata document could not be fetched safely (it "
                "must be a publicly reachable https URL).",
            ) from exc
        try:
            document = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OAuthError(
                "invalid_client_metadata",
                "the client-id metadata document is not valid JSON.",
            ) from exc
        return validate_metadata(document, expected_client_id=client_id)


class StaticCimdFetcher(CimdFetcher):
    """A :class:`CimdFetcher` serving documents from memory, for tests.

    Exists so the CIMD *flow* can be exercised without an outbound network
    call. It performs the same :func:`validate_metadata` checks as the real
    fetcher — only the transport is replaced, so a test cannot accidentally
    prove that validation it skipped works.
    """

    def __init__(self, documents: dict[str, Any] | None = None) -> None:
        self.documents: dict[str, Any] = dict(documents or {})

    async def fetch(self, client_id: str) -> dict[str, Any]:
        if not is_cimd_client_id(client_id):
            raise OAuthError(
                "invalid_client_metadata",
                "a client-id metadata document URL must be https with no fragment.",
            )
        if client_id not in self.documents:
            raise OAuthError(
                "invalid_client_metadata",
                "the client-id metadata document could not be fetched.",
            )
        return validate_metadata(self.documents[client_id], expected_client_id=client_id)


#: Hosts the loopback-port exemption below applies to. The RFC names the
#: loopback IP literals; ``localhost`` is included because real native
#: clients (Claude Code's published CIMD document among them) register it,
#: and :func:`validate_redirect_uri` already accepts it as loopback.
_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def match_redirect_uri(registered: Sequence[str], presented: str) -> str:
    """Return ``presented`` if it matches a registered redirect URI.

    Exact string comparison, deliberately: prefix or "same origin" matching
    is how open redirectors get built, and OAuth 2.1 §4.1.3 requires exact
    matching for this reason.

    One spec-mandated carve-out (RFC 8252 §7.3, folded into OAuth 2.1
    §10.3.3, issue #233): a native client redirecting to an ``http``
    loopback URI picks an **ephemeral port at request time**, so for those
    URIs — and only those — the port is ignored. Everything else must still
    agree exactly: scheme (``http``), hostname (the same loopback name, no
    cross-host equivalence), path, query, and no fragment. Without this,
    a client whose registered loopback URI carries no port (Claude Code's
    default CIMD registration) can never complete a login.

    Raises:
        OAuthError: ``invalid_redirect_uri`` on any mismatch.
    """
    if presented in registered:
        return presented
    if _matches_loopback_port_variant(registered, presented):
        return presented
    raise OAuthError(
        "invalid_redirect_uri",
        "the redirect_uri does not exactly match one this client registered.",
    )


def _matches_loopback_port_variant(registered: Sequence[str], presented: str) -> bool:
    """RFC 8252 §7.3: match an http-loopback URI ignoring only its port."""
    parts = urlsplit(presented)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS or parts.fragment:
        return False
    for candidate in registered:
        known = urlsplit(candidate)
        if (
            known.scheme == "http"
            and known.hostname == parts.hostname
            and known.path == parts.path
            and known.query == parts.query
            and not known.fragment
        ):
            return True
    return False


__all__ = [
    "ALLOWED_GRANT_TYPES",
    "MAX_DOCUMENT_BYTES",
    "CimdFetcher",
    "StaticCimdFetcher",
    "is_cimd_client_id",
    "match_redirect_uri",
    "validate_metadata",
    "validate_redirect_uri",
]
