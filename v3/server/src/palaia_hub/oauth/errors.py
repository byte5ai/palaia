"""RFC 6749 §5.2 error codes as one exception type, plus its JSON body.

Every caller-facing failure in this package raises :class:`OAuthError`, and
:mod:`palaia_hub.oauth.routes` turns it into the exact JSON body and status
an OAuth client expects. Two rules hold everywhere:

1. **``description`` is written for the operator reading a log or a browser
   tab, never for a client to parse — and it never contains a credential.**
   No authorization code, refresh token, client secret, password, session id
   or ``code_verifier`` may appear in one, not even truncated. The redaction
   filter (:mod:`palaia_hub.logging`) is the safety net; not putting secrets
   in the message is the actual defense.
2. **The same code for every reason a grant can fail.** An attacker probing
   ``/token`` learns "this did not work", never *which* of "unknown token",
   "revoked", "expired", "already spent past its grace window" applied — the
   same discipline :meth:`palaia_hub.auth.store.TokenStore.verify` follows.
"""

from __future__ import annotations

from typing import Any

#: RFC 6749 §4.1.2.1 / §5.2 and RFC 8707 §2 codes this package raises.
#: Kept as a literal tuple so a typo becomes a test failure rather than an
#: error code no client recognizes.
ERROR_CODES = (
    "invalid_request",
    "invalid_client",
    "invalid_grant",
    "unauthorized_client",
    "unsupported_grant_type",
    "unsupported_response_type",
    "invalid_scope",
    "invalid_target",
    "access_denied",
    "server_error",
    "invalid_client_metadata",
    "invalid_redirect_uri",
)


class OAuthError(Exception):
    """One OAuth protocol error, ready to render as JSON or an error page.

    Args:
        error: an :data:`ERROR_CODES` member.
        description: operator-facing detail. Never a credential (see the
            module docstring).
        status_code: HTTP status to answer with. Defaults follow RFC 6749:
            400 for most, 401 for ``invalid_client``.
        headers: extra response headers (e.g. ``WWW-Authenticate`` on a
            failed client authentication).
    """

    def __init__(
        self,
        error: str,
        description: str,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if error not in ERROR_CODES:
            raise ValueError(f"unknown OAuth error code {error!r}; add it to ERROR_CODES")
        super().__init__(f"{error}: {description}")
        self.error = error
        self.description = description
        self.status_code = status_code if status_code is not None else _default_status(error)
        self.headers = dict(headers or {})

    def body(self) -> dict[str, Any]:
        """The RFC 6749 §5.2 JSON body for this error."""
        return {"error": self.error, "error_description": self.description}


def _default_status(error: str) -> int:
    if error == "invalid_client":
        return 401
    if error == "server_error":
        return 500
    return 400


__all__ = ["ERROR_CODES", "OAuthError"]
