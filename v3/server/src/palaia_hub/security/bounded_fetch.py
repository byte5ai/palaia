"""One HTTP GET whose body is capped *while it is read* (issue #353).

Every outbound fetch the hub makes to a host it does not control — the
official registry, the curated index, the update check — is size-capped.
Until this module the cap was enforced after ``await client.get(...)`` had
already buffered the whole body: a host answering with gigabytes made the
hub hold gigabytes, then reject them. Now the response is streamed; the
``Content-Length`` header is refused up front when it already exceeds the
cap, and the read is abandoned the moment the bytes received cross it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


class ResponseTooLargeError(RuntimeError):
    """The body exceeded ``max_bytes``; reading stopped there."""

    def __init__(self, *, limit: int, received: int | None = None, declared: int | None = None):
        self.limit = limit
        self.received = received
        self.declared = declared
        if declared is not None:
            detail = f"declares {declared} bytes, more than the {limit} allowed"
        else:
            detail = f"exceeded {limit} bytes; stopped reading at {received}"
        super().__init__(f"response too large ({detail})")


@dataclass(frozen=True, slots=True)
class BoundedResponse:
    """What :func:`get_bounded` hands back: status, headers, and a body that
    is guaranteed to be at most ``max_bytes`` long."""

    status_code: int
    headers: httpx.Headers
    content: bytes

    def json(self) -> Any:
        """Decode the body as JSON (``ValueError`` when it is not)."""
        return json.loads(self.content)


async def get_bounded(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> BoundedResponse:
    """``GET url`` and return at most ``max_bytes`` of body.

    Raises :class:`ResponseTooLargeError` as soon as the cap is known to be
    exceeded — from the ``Content-Length`` header before any body byte is
    read, or from the running count while streaming. Network and timeout
    errors surface as the usual :mod:`httpx` exceptions, whether they
    happen on connect or mid-body. An error status (``>= 400``) is returned
    with an empty body: callers act on the status, and an error page is
    never worth buffering.
    """
    kwargs: dict[str, Any] = {"headers": headers, "params": params}
    if timeout is not None:
        kwargs["timeout"] = timeout
    async with client.stream("GET", url, **kwargs) as response:
        if response.status_code >= 400:
            return BoundedResponse(response.status_code, response.headers, b"")
        declared = response.headers.get("content-length")
        if declared is not None and declared.strip().isdigit() and int(declared) > max_bytes:
            raise ResponseTooLargeError(limit=max_bytes, declared=int(declared))
        chunks: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes():
            received += len(chunk)
            if received > max_bytes:
                raise ResponseTooLargeError(limit=max_bytes, received=received)
            chunks.append(chunk)
    return BoundedResponse(response.status_code, response.headers, b"".join(chunks))


__all__ = ["BoundedResponse", "ResponseTooLargeError", "get_bounded"]
