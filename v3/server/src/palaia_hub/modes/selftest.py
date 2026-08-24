"""The public-URL self-test (SPEC-205 deliverable #2's "no fake green").

The wizard's whole trust proposition rests on this: it never *claims* a
public URL is reachable without the hub itself fetching it. This module
does exactly one thing — an HTTP GET against ``<public_url>/api/info``
(the hub's own always-on metadata endpoint, see :mod:`palaia_hub.app`) —
and reports what actually happened: a 2xx response is reachable and honest
about round-trip time; anything else (a non-2xx status, a connection
error, a timeout, TLS failure) is reported as unreachable with the real
reason, never coerced into a generic "failed".
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

_SELF_TEST_PATH = "/api/info"
_DEFAULT_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    checked_url: str
    reachable: bool
    #: HTTP status code, when a response was received at all.
    status_code: int | None
    latency_ms: float | None
    #: Empty when reachable; the real failure reason otherwise (never a
    #: generic "failed" — see this module's docstring).
    error: str


async def check_public_url(
    public_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> SelfTestResult:
    """Fetch ``<public_url>/api/info`` and report honestly what happened.

    Args:
        client: an existing :class:`httpx.AsyncClient` to reuse (tests pass
            one wired to an ``httpx.MockTransport`` or an in-process ASGI
            transport so this never needs a real network round-trip);
            omitted, a real one is opened and closed for this one call.
    """
    url = public_url.rstrip("/") + _SELF_TEST_PATH
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    start = time.monotonic()
    try:
        response = await http.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return SelfTestResult(
            checked_url=url,
            reachable=False,
            status_code=None,
            latency_ms=None,
            error=f"timed out after {timeout:.0f}s — nothing answered at {url}.",
        )
    except httpx.RequestError as exc:
        return SelfTestResult(
            checked_url=url,
            reachable=False,
            status_code=None,
            latency_ms=None,
            error=f"could not connect to {url}: {exc}",
        )
    finally:
        if owns_client:
            await http.aclose()
    latency_ms = (time.monotonic() - start) * 1000
    if response.status_code >= 400:
        return SelfTestResult(
            checked_url=url,
            reachable=False,
            status_code=response.status_code,
            latency_ms=latency_ms,
            error=f"{url} answered with HTTP {response.status_code}, not this hub's metadata.",
        )
    return SelfTestResult(
        checked_url=url,
        reachable=True,
        status_code=response.status_code,
        latency_ms=latency_ms,
        error="",
    )


__all__ = ["SelfTestResult", "check_public_url"]
