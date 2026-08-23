"""PKCE (RFC 7636), S256 only.

``plain`` is not implemented and never will be: it makes the challenge equal
to the verifier, so anyone who can read the authorization request can
complete the exchange — the exact attack PKCE exists to stop. OAuth 2.1
requires S256 for public clients, and every MCP client in the 2026 landscape
sends it. A request carrying ``code_challenge_method=plain`` is rejected as
``invalid_request`` rather than downgraded.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets

from .errors import OAuthError

#: RFC 7636 §4.1: the verifier is 43–128 characters of the unreserved set.
_VERIFIER_RE = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")

#: RFC 7636 §4.2 base64url-without-padding of a SHA-256 digest: 43 chars.
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9\-_]{43}$")

S256 = "S256"


def challenge_for(code_verifier: str) -> str:
    """Return the S256 challenge for ``code_verifier`` (RFC 7636 §4.2)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def validate_challenge(code_challenge: str | None, method: str | None) -> str:
    """Validate an authorization request's PKCE parameters.

    Returns the challenge to store alongside the authorization code.

    Raises:
        OAuthError: ``invalid_request`` if the challenge is missing or
            malformed, or the method is anything but ``S256``.
    """
    if method is not None and method != S256:
        raise OAuthError(
            "invalid_request",
            f"code_challenge_method must be {S256!r}; 'plain' offers no protection "
            f"and is not accepted. Fix: send a base64url SHA-256 challenge.",
        )
    if not code_challenge:
        raise OAuthError(
            "invalid_request",
            "code_challenge is required (PKCE is mandatory for every client). "
            "Fix: send code_challenge with code_challenge_method=S256.",
        )
    if not _CHALLENGE_RE.match(code_challenge):
        raise OAuthError(
            "invalid_request",
            "code_challenge is not a base64url-encoded SHA-256 digest (43 "
            "characters, no padding). Fix: send S256(code_verifier).",
        )
    return code_challenge


def verify_verifier(code_verifier: str | None, code_challenge: str) -> None:
    """Check a token request's ``code_verifier`` against the stored challenge.

    Raises:
        OAuthError: ``invalid_grant`` on any mismatch — the same code the
            unknown/expired/spent-code paths use, so a client learns only
            that the exchange failed.
    """
    if not code_verifier or not _VERIFIER_RE.match(code_verifier):
        raise OAuthError(
            "invalid_grant",
            "the code_verifier is missing or not 43–128 unreserved characters "
            "(RFC 7636 §4.1). Fix: send the verifier whose S256 digest was used "
            "as code_challenge.",
        )
    if not secrets.compare_digest(challenge_for(code_verifier), code_challenge):
        raise OAuthError(
            "invalid_grant",
            "the code_verifier does not match the code_challenge from the "
            "authorization request.",
        )


__all__ = ["S256", "challenge_for", "validate_challenge", "verify_verifier"]
