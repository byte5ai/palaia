"""Who a request is from, for rate limiting (SPEC-502 deliverable #2).

The failed-attempt limiter (:mod:`palaia_hub.modes.rate_limit`) keys its
buckets on the caller's address. Taken naively from the ASGI ``client``
tuple, that address is correct for a hub a client reaches directly — and
**always ``127.0.0.1``** for the packaged container image, where nginx is
the only public listener and the hub binds loopback behind it. The audit
that produced this module found both halves of that failure at once: an
attacker on the container image got no per-address limit (every attempt from
everywhere shares one bucket), and once the shared bucket filled, *every*
user was locked out by whoever filled it.

**The rule.** Trust ``X-Forwarded-For`` only when the request's immediate
peer is loopback, and then take the **last** entry, not the first. Both
halves matter:

* *Only from loopback* — a header is client-controlled. Off loopback the
  hub is talking to the caller directly and the peer address is the truth,
  so the header is ignored entirely and cannot be used to forge an identity
  or to escape a bucket.
* *The last entry* — nginx appends the peer it actually saw
  (``$proxy_add_x_forwarded_for`` is ``"$http_x_forwarded_for,
  $remote_addr"``), so a caller who sends their own ``X-Forwarded-For:
  1.2.3.4`` gets it pushed left and the real address appended on the right.
  Reading the first entry — the usual mistake — would read the attacker's
  own forgery.

A hub reached directly on the LAN never has a loopback peer for a remote
caller, so this changes nothing there; a hub reached through the container's
nginx now limits per real client address.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
_Receive = Callable[[], Awaitable[dict[str, Any]]]

#: What a bucket is keyed on when the caller cannot be identified at all
#: (an ASGI scope with no ``client``, as in some test transports).
UNKNOWN_CLIENT = "unknown"


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def _forwarded_for(scope: Scope) -> str | None:
    """The last ``X-Forwarded-For`` entry, or ``None`` if there is no header."""
    headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
    for name, value in headers:
        if name == b"x-forwarded-for":
            entries = [part.strip() for part in value.decode("latin-1").split(",")]
            trailing = [entry for entry in entries if entry]
            if trailing:
                return trailing[-1]
            return None
    return None


def client_ip_for_scope(scope: Scope) -> str:
    """The address a rate-limit bucket for ``scope`` should be keyed on."""
    client = scope.get("client")
    peer = client[0] if client else None
    if peer is None:
        return UNKNOWN_CLIENT
    if _is_loopback(str(peer)):
        forwarded = _forwarded_for(scope)
        if forwarded:
            return forwarded
    return str(peer)


__all__ = ["UNKNOWN_CLIENT", "client_ip_for_scope"]
