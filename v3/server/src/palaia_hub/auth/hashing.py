"""argon2id hashing for client-token secrets, with a constant-time-miss helper.

This is the only module in the codebase that calls into ``argon2``. Every
other piece of the token store goes through :func:`hash_secret` /
:func:`verify_secret` — a security surface stays auditable by staying in
exactly one place.

``argon2.PasswordHasher()`` defaults to the argon2id variant (has been since
argon2-cffi 18.2), which is what SPEC-108 requires. Its ``verify()`` re-hashes
the candidate secret and compares the two digests; that comparison is done
by the underlying C library in constant time by design — this module adds
nothing on top for the *hash-mismatch* case (the acceptance criterion's
"timing-safe comparison"), but see :func:`spend_constant_time_miss` for the
one case argon2 itself cannot cover: a token whose id was never issued at
all, which never reaches ``verify()`` and would otherwise return in
near-zero time.
"""

from __future__ import annotations

import contextlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# A hash of a value nobody will ever present as a real secret. Verifying
# against it spends the same wall-clock time as a real (mismatching) verify,
# so "no token with this id exists" and "this id exists but the secret is
# wrong" cost the same — the id half of a token is not meant to be secret
# (see store.py's module docstring), but paying this cost anyway is cheap
# insurance against relying on that assumption elsewhere.
_DUMMY_HASH = _hasher.hash("palaia-constant-time-padding-not-a-real-token")


def hash_secret(secret: str) -> str:
    """Return the argon2id hash of ``secret``, ready to store."""
    return _hasher.hash(secret)


def verify_secret(secret: str, stored_hash: str) -> bool:
    """Constant-time-compare ``secret`` against ``stored_hash``.

    Returns ``False`` for a mismatch, a malformed hash, or any other
    argon2 verification failure — never raises for caller-facing reasons.
    """
    try:
        _hasher.verify(stored_hash, secret)
    except (VerifyMismatchError, VerificationError):
        return False
    return True


def spend_constant_time_miss() -> None:
    """Burn one argon2 verify's worth of time on a fixed dummy hash.

    Call this on a "no such token id" path so it costs the same as a real
    mismatch (see the module docstring and :data:`_DUMMY_HASH`).
    """
    with contextlib.suppress(VerifyMismatchError, VerificationError):
        _hasher.verify(_DUMMY_HASH, secrets.token_urlsafe(32))


__all__ = ["hash_secret", "spend_constant_time_miss", "verify_secret"]
