"""The single local owner account, its login form, and its session cookie.

Scope, precisely: this SPEC gives the authorization server exactly **one**
door — a local account whose password the operator sets from the CLI.
GitHub/Google/OIDC sign-in is SPEC-204, and MASTERPLAN §5.5's "one door only"
rule is why they arrive as a *replacement* for this password rather than
alongside it ("two doors into the same room mean the weaker one decides how
strong the room is"). :meth:`palaia_hub.oauth.store.OAuthStore.set_owner`
enforces the "one account" half structurally by clearing the table first.

Defenses, and why each is here:

* **argon2id** for the password, via :mod:`palaia_hub.auth.hashing` — the one
  module in this codebase that talks to argon2, reused rather than
  reconfigured. A password is the only low-entropy secret in the system, so it
  is the only one that needs a KDF.
* **A constant-time miss** on "no account exists yet" and on an unknown
  username, so the form cannot be used to discover whether the hub has been
  set up.
* **Per-account throttling** of failed attempts. In-memory on purpose: it must
  not become a write amplifier on the store, and losing the counter on restart
  is an acceptable trade for a single-owner hub (an attacker who can restart
  the hub already owns the box).
* **A double-submit CSRF token.** The login form is a state-changing POST that
  an attacker's page could otherwise submit with *their* credentials, logging
  the victim's browser into the attacker's session — login CSRF, which in an
  OAuth authorization server means the victim authorizing a client under the
  attacker's identity. The token lives in a cookie and a hidden field and must
  match.
* **Cookies** are ``HttpOnly`` (no script can read a session id),
  ``SameSite=Lax`` (a cross-site POST carries no session cookie, while the
  ordinary top-level redirect back from ``/authorize`` still does), ``Path=/``,
  and ``Secure`` whenever the issuer is https.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..auth.hashing import hash_secret as hash_password
from ..auth.hashing import spend_constant_time_miss, verify_secret
from .errors import OAuthError
from .secrets_util import new_secret
from .store import OAuthStore

logger = logging.getLogger("palaia_hub.oauth.login")

SESSION_COOKIE = "palaia_oauth_session"
CSRF_COOKIE = "palaia_oauth_csrf"
#: Issue #345: binds an identity-provider sign-in to the browser that
#: started it. Set on ``/oauth/idp/start``, required back on the callback.
IDP_NONCE_COOKIE = "palaia_oauth_idp"
CSRF_FIELD = "csrf_token"
#: The request header the double-submit token is echoed in by anything that
#: is not an HTML form — the dashboard's API client, and the sign-out call.
#: Lives here, with the cookie and the form field it is paired against, so
#: the whole double-submit contract reads in one place;
#: :mod:`palaia_hub.admin_session` re-exports it under the same name for the
#: middleware that enforces it.
CSRF_HEADER = "x-palaia-csrf"

#: How long a browser login session lives. Short by web-app standards
#: because its only job is to carry the operator from ``/login`` back to
#: ``/authorize`` and to spare them a password on the next client they
#: connect the same afternoon.
DEFAULT_SESSION_TTL_SECONDS = 12 * 3600

#: Failed-attempt throttle: after this many failures for one username, the
#: account stops accepting attempts for :data:`LOCKOUT_SECONDS`.
MAX_FAILED_ATTEMPTS = 8
LOCKOUT_SECONDS = 300


@dataclass
class _AttemptState:
    failures: int = 0
    locked_until: float = 0.0


@dataclass
class LoginThrottle:
    """In-memory failed-attempt counter, keyed by username.

    Thread-safe because login verification runs on a worker thread (argon2 is
    CPU-bound and must not block the event loop).
    """

    max_failures: int = MAX_FAILED_ATTEMPTS
    lockout_seconds: int = LOCKOUT_SECONDS
    #: Monotonic time source. Injectable so a test can cross a lockout window
    #: without sleeping through it; a lockout is deliberately measured on the
    #: monotonic clock so a wall-clock change cannot shorten one.
    clock: Callable[[], float] = time.monotonic
    _states: dict[str, _AttemptState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, username: str, *, now: float | None = None) -> None:
        """Raise if ``username`` is currently locked out."""
        moment = self.clock() if now is None else now
        with self._lock:
            state = self._states.get(username)
            if state is not None and state.locked_until > moment:
                remaining = int(state.locked_until - moment) + 1
                raise OAuthError(
                    "access_denied",
                    f"too many failed sign-in attempts; try again in {remaining}s.",
                    status_code=429,
                )

    def record_failure(self, username: str, *, now: float | None = None) -> None:
        moment = self.clock() if now is None else now
        with self._lock:
            state = self._states.setdefault(username, _AttemptState())
            state.failures += 1
            if state.failures >= self.max_failures:
                state.locked_until = moment + self.lockout_seconds
                state.failures = 0
                logger.warning(
                    "locking sign-in for %r for %ds after repeated failures",
                    username,
                    self.lockout_seconds,
                )

    def record_success(self, username: str) -> None:
        with self._lock:
            self._states.pop(username, None)


def set_owner_password(store: OAuthStore, username: str, password: str, *, now: int) -> None:
    """Create or replace the owner account.

    Raises:
        OAuthError: ``invalid_request`` for an empty username or a password
            below the minimum length. The minimum is deliberately modest and
            unopinionated beyond length: this account is reachable only where
            the operating mode says the hub is reachable, and a length floor
            is the one rule that is never wrong.
    """
    if not username.strip():
        raise OAuthError("invalid_request", "the owner account needs a username.")
    if len(password) < 12:
        raise OAuthError(
            "invalid_request",
            "the owner password must be at least 12 characters. Fix: use a "
            "passphrase, or generate one with your password manager.",
        )
    store.set_owner(username.strip(), hash_password(password), now)
    logger.info("owner account set for %r (every existing login session was cleared)", username)


def verify_owner_password(
    store: OAuthStore, username: str, password: str, *, throttle: LoginThrottle
) -> str:
    """Verify a sign-in attempt; return the account's username.

    Raises:
        OAuthError: ``access_denied`` for a wrong username, a wrong password,
            a hub with no owner account yet, or a throttled account — one
            message for all of them, so the form reveals nothing.
    """
    throttle.check(username)
    owner = store.get_owner()
    denied = OAuthError(
        "access_denied",
        "sign-in failed. Fix: check the username and password; the operator sets "
        "them with `palaia-hub oauth set-password` (or the dashboard's first-run "
        "setup, while no account exists).",
        status_code=401,
    )
    if owner is None:
        # No account configured: cost the same as a real verify so the form
        # cannot be used to detect an un-provisioned hub.
        spend_constant_time_miss()
        raise denied
    stored_username, password_hash = owner
    if username != stored_username:
        spend_constant_time_miss()
        throttle.record_failure(username)
        raise denied
    if not verify_secret(password, password_hash):
        throttle.record_failure(username)
        raise denied
    throttle.record_success(username)
    return stored_username


def new_csrf_token() -> str:
    """A fresh double-submit CSRF token."""
    return new_secret()


__all__ = [
    "CSRF_COOKIE",
    "CSRF_FIELD",
    "CSRF_HEADER",
    "DEFAULT_SESSION_TTL_SECONDS",
    "LOCKOUT_SECONDS",
    "MAX_FAILED_ATTEMPTS",
    "SESSION_COOKIE",
    "LoginThrottle",
    "new_csrf_token",
    "set_owner_password",
    "verify_owner_password",
]
