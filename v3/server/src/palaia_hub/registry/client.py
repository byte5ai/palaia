"""Client for the official MCP registry (SPEC-303 deliverable #1).

Talks to ``registry.modelcontextprotocol.io``'s API v0.1 — **frozen**, per
``v3/research/mcp-landscape-2026.md`` §4 ("no breaking changes" since
2025-10-24) — using its ``GET /v0/servers`` (search/list) and
``GET /v0/servers/{id}`` (detail) endpoints.

Three properties this SPEC requires, all here:

1. **Never hangs.** Every request carries both a connect and a total
   timeout (``timeout_seconds``); a slow/dead registry fails fast, never
   leaves a dashboard request hanging.
2. **Size-capped.** A response body over ``max_bytes`` is rejected as if
   the fetch had failed — a misbehaving or compromised registry cannot
   make the hub buffer an unbounded body.
3. **Cached with honest staleness.** Every successful fetch is written to
   an on-disk :class:`~palaia_hub.registry.cache.DiskCache` keyed by the
   exact request URL. A fresh within-TTL cache hit is served without a
   network round-trip; a fetch that fails outright (offline, timeout,
   5xx) falls back to whatever is cached, however old, marked ``stale``
   and ``offline`` with the reason named — never a hang, never a silent
   empty result when a cache exists.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import palaia_home
from .cache import DiskCache
from .models import RegistrySearchResult, RegistryServer

logger = logging.getLogger("palaia_hub.registry.client")

DEFAULT_BASE_URL = "https://registry.modelcontextprotocol.io"
DEFAULT_TTL_SECONDS = 3600.0
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
CACHE_RELATIVE_PATH = "registry_cache"


class RegistryOfflineError(RuntimeError):
    """Raised only when there is truly nothing to serve: the fetch failed
    and no cached copy — fresh or stale — exists for this request."""


def _server_from_raw(raw: dict[str, Any]) -> RegistryServer:
    server = raw.get("server", raw)
    meta = raw.get("_meta", {})
    official = meta.get("io.modelcontextprotocol.registry/official", {})
    server_id = str(official.get("id") or server.get("id") or server.get("name") or "")
    return RegistryServer(
        id=server_id,
        name=str(server.get("name", server_id)),
        description=str(server.get("description", "")),
        version=server.get("version"),
        raw=raw,
    )


class RegistryClient:
    """Search/detail against the official registry, cached and capped."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        cache_dir: Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._cache = DiskCache(cache_dir or (palaia_home() / CACHE_RELATIVE_PATH))
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _fetch(
        self, path: str, params: dict[str, Any], *, single: bool = False
    ) -> RegistrySearchResult:
        cache_key = f"{self.base_url}{path}?{sorted(params.items())}"
        cached = self._cache.get(cache_key)
        if cached is not None and cached.age_seconds < self.ttl_seconds:
            servers = tuple(_server_from_raw(item) for item in cached.payload)
            return RegistrySearchResult(
                servers=servers, stale=False, offline=False, fetched_at=cached.fetched_at
            )

        try:
            response = await self._client.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout_seconds
            )
        except httpx.TimeoutException:
            return self._fallback(cached, cache_key, f"timed out after {self.timeout_seconds:.0f}s")
        except httpx.RequestError as exc:
            return self._fallback(cached, cache_key, f"network error: {exc}")

        if response.status_code == 404:
            # A definitive "no such server" — not an outage, so it is never
            # a fallback candidate; the caller (RegistryClient.detail) turns
            # this empty result into `None` rather than raising.
            return RegistrySearchResult(
                servers=(), stale=False, offline=False, fetched_at=time.time()
            )
        if response.status_code >= 400:
            return self._fallback(
                cached, cache_key, f"registry answered HTTP {response.status_code}"
            )

        content_length = len(response.content)
        if content_length > self.max_bytes:
            return self._fallback(
                cached, cache_key, f"response too large ({content_length} > {self.max_bytes} bytes)"
            )

        try:
            body = response.json()
        except ValueError:
            return self._fallback(cached, cache_key, "registry returned invalid JSON")

        if single:
            items = [] if not isinstance(body, dict) else [body]
        else:
            items = body.get("servers", body if isinstance(body, list) else [])
        now = time.time()
        self._cache.set(cache_key, items, fetched_at=now)
        servers = tuple(_server_from_raw(item) for item in items)
        return RegistrySearchResult(servers=servers, stale=False, offline=False, fetched_at=now)

    def _fallback(self, cached: Any, cache_key: str, reason: str) -> RegistrySearchResult:
        if cached is None:
            logger.warning("registry unreachable and no cache for %s: %s", cache_key, reason)
            raise RegistryOfflineError(reason)
        logger.warning(
            "registry unreachable, serving cached copy from %.0fs ago: %s",
            cached.age_seconds,
            reason,
        )
        servers = tuple(_server_from_raw(item) for item in cached.payload)
        return RegistrySearchResult(
            servers=servers,
            stale=True,
            offline=True,
            fetched_at=cached.fetched_at,
            note=reason,
        )

    async def search(self, query: str = "", *, limit: int = 30) -> RegistrySearchResult:
        params: dict[str, Any] = {"limit": limit}
        if query:
            params["search"] = query
        return await self._fetch("/v0/servers", params)

    async def detail(self, server_id: str) -> RegistryServer | None:
        result = await self._fetch(f"/v0/servers/{server_id}", {}, single=True)
        if not result.servers:
            return None
        return result.servers[0]


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "RegistryClient",
    "RegistryOfflineError",
]
