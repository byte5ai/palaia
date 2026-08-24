"""HMAC-SHA256 signing for outbound webhook deliveries (SPEC-201 deliverable #2).

Header names a receiver checks against, mirroring the well-worn GitHub/
Stripe shape so an integrator's existing verification code mostly just
works:

- ``X-Palaia-Signature``: ``sha256=<hex hmac>`` over the raw request body,
  keyed by the hook's secret.
- ``X-Palaia-Event``: the event name (``memory.entry.created``, ...).
- ``X-Palaia-Event-Id``: the event's idempotency key — the same id on every
  retry of the same delivery, so a receiver that has already processed it
  can safely no-op on a repeat.
- ``X-Palaia-Delivery-Attempt``: 1 on the first attempt, incrementing on
  each retry.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "X-Palaia-Signature"
EVENT_HEADER = "X-Palaia-Event"
EVENT_ID_HEADER = "X-Palaia-Event-Id"
ATTEMPT_HEADER = "X-Palaia-Delivery-Attempt"


def sign(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature of ``body`` keyed by ``secret``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(secret: str, body: bytes, signature: str) -> bool:
    """Constant-time check that ``signature`` matches ``sign(secret, body)``.

    Provided for receivers written against this same module (tests, and any
    future in-repo webhook consumer); an external receiver reimplements
    this against ``secret`` on its own side.
    """
    return hmac.compare_digest(sign(secret, body), signature)


__all__ = [
    "ATTEMPT_HEADER",
    "EVENT_HEADER",
    "EVENT_ID_HEADER",
    "SIGNATURE_HEADER",
    "sign",
    "verify",
]
