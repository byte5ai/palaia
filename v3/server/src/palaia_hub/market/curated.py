"""The curated palaia add-on index (SPEC-303 deliverable #2).

A **signed JSON document**, fixed shape::

    {schema_version, generated_at, entries: [...], signature}

fetched from a configurable URL and verified against a pinned Ed25519
public key. The key is baked into the package
(:data:`DEFAULT_PUBLIC_KEY_B64`) and may be replaced only through the
owner-only ``config.yaml`` (``market.public_key``, SPEC-303 / issue #321)
— never fetched, never settable over REST, because a trust anchor that a
remote caller could move would defeat the point. ``signature`` is a
base64-encoded Ed25519 signature over the canonical JSON encoding
(``json.dumps(..., sort_keys=True, separators=(",", ":"))``) of the
document *without* the ``signature`` key itself.

A tampered document — wrong signature, wrong (attacker's) key, or a
``generated_at`` older than the last copy we already trusted (a rollback/
downgrade attack) — is refused loudly (a WARNING naming the exact reason)
and this module falls back to the last verified copy on disk. When there
is no such copy, refusal means an empty curated index, never a
half-trusted document silently accepted.

**Fetched at most once per TTL, not once per request** (issue #321). The
outcome of every fetch — a verified document *or* the reason it failed —
is recorded in an on-disk TTL cache next to the last-good copy, mirroring
:mod:`palaia_hub.registry.client`. Within :data:`DEFAULT_TTL_SECONDS` of a
success the last-good copy is served with no network round-trip; within
:data:`DEFAULT_FAILURE_TTL_SECONDS` of a failure the fallback is served
without retrying, so an unreachable index host costs one bounded timeout
per five minutes rather than one per installed add-on per page load.
"""

from __future__ import annotations

import base64
import importlib.resources
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..config import palaia_home
from ..registry.cache import DiskCache
from ..security.files import harden_file
from .models import MarketEntry, SourceLocator

logger = logging.getLogger("palaia_hub.market.curated")

#: The default pinned Ed25519 public key (raw 32 bytes, base64), baked
#: into the package. It is the key the bundled **starter** index was
#: signed with, and its private half was discarded right after that
#: signing (see ``v3/tools/README.md`` and ``v3/tools/sign_market_index.py``)
#: — so until whoever publishes the real palaia curated index mints a
#: keypair, signs and publishes ``market-index.json`` at
#: :data:`DEFAULT_INDEX_URL`, and either replaces this constant in a
#: release or sets ``market.public_key`` in ``config.yaml``, no fetched
#: document can verify and every hub serves the starter index (issue
#: #321). The key is never fetched and never settable over REST.
DEFAULT_PUBLIC_KEY_B64 = "xh8oKQEO/x7pfXrfqieqjkUc866ZcDPuCvkI3MhSN8k="

DEFAULT_INDEX_URL = "https://index.palaia.dev/market-index.json"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
#: How long a verified fetch is served from disk before the URL is asked
#: again (same knob as :data:`palaia_hub.registry.client.DEFAULT_TTL_SECONDS`).
DEFAULT_TTL_SECONDS = 3600.0
#: How long a *failed* fetch (unreachable host, refused document) is
#: remembered before retrying — the negative cache that keeps a dead
#: index URL from costing one 8 s timeout per marketplace request.
DEFAULT_FAILURE_TTL_SECONDS = 300.0
LAST_GOOD_RELATIVE_PATH = "market_curated_index.json"
CACHE_RELATIVE_PATH = "market_curated_cache"

SCHEMA_VERSION = 1


class IndexVerificationError(RuntimeError):
    """A curated index document was refused. ``reason`` names why —
    always logged as a WARNING by :meth:`CuratedIndexClient.fetch`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CuratedIndexResult:
    entries: tuple[MarketEntry, ...]
    generated_at: str
    #: True whenever this is not a document freshly verified this call —
    #: either the last-verified copy on disk (network failure or a
    #: refused document) or, in principle, never for a fresh success.
    stale: bool
    #: Empty on a clean fresh fetch; otherwise the reason the fallback was
    #: used (network error, or the exact verification failure).
    warning: str = ""


def load_starter_index() -> dict[str, Any]:
    """The small signed starter index shipped in the package (SPEC-303
    deliverable #2's "ship a small starter index as a repo file") — a
    fresh hub that has never fetched a real curated index, and can't
    reach one right now, still has something real to browse rather than
    an empty marketplace. See ``v3/tools/README.md`` for how it was
    produced (and why its signing key was discarded afterward)."""
    data = importlib.resources.files("palaia_hub.market") / "data" / "starter-index.json"
    return json.loads(data.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def canonical_bytes(document: dict[str, Any]) -> bytes:
    """The exact bytes a signature is computed over: the document minus
    its own ``signature`` key, canonical JSON (sorted keys, no whitespace).
    """
    payload = {k: v for k, v in document.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _entry_from_raw(raw: dict[str, Any], *, provenance: str) -> MarketEntry:
    source = raw["source"]
    if not isinstance(source, dict):
        # A bare-string source in a starter/manual index is treated as a
        # URL locator — the least-surprising default for "just a link".
        source = {"type": "url", "value": source}
    return MarketEntry(
        id=raw["id"],
        name=raw["name"],
        one_liner=raw["one_liner"],
        kind=raw["kind"],
        source=SourceLocator(**source),
        config_schema=raw.get("config_schema"),
        permissions=list(raw.get("permissions", [])),
        maintainer=raw["maintainer"],
        verified=bool(raw.get("verified", False)),
        provenance=provenance,  # type: ignore[arg-type]
    )


def verify_index_document(
    document: dict[str, Any],
    *,
    public_key_b64: str,
    known_generated_at: str | None,
) -> None:
    """Raise :class:`IndexVerificationError` naming the exact reason, or
    return silently when the document is authentic and not a rollback."""
    for key in ("schema_version", "generated_at", "entries", "signature"):
        if key not in document:
            raise IndexVerificationError(f"curated index document is missing '{key}'")
    if document["schema_version"] != SCHEMA_VERSION:
        raise IndexVerificationError(
            f"curated index schema_version {document['schema_version']!r} is not "
            f"the one this hub understands ({SCHEMA_VERSION})"
        )
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        signature = base64.b64decode(document["signature"])
    except Exception as exc:  # noqa: BLE001 - any decode failure is "bad signature"
        raise IndexVerificationError(f"curated index signature is malformed: {exc}") from exc
    try:
        public_key.verify(signature, canonical_bytes(document))
    except InvalidSignature as exc:
        raise IndexVerificationError(
            "curated index signature does not match the pinned public key "
            "(tampered document, or signed with the wrong key)"
        ) from exc
    if known_generated_at is not None and str(document["generated_at"]) < known_generated_at:
        raise IndexVerificationError(
            f"curated index generated_at {document['generated_at']!r} is older than the "
            f"last verified copy ({known_generated_at!r}) — refusing a downgrade/rollback"
        )


class _FetchFailure(Exception):
    """The index could not be downloaded as a JSON object. ``reason`` is
    the plain-language line that becomes the result's ``warning``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CuratedIndexClient:
    """Fetch + verify the curated index, with a signed-fallback-to-disk
    and an on-disk TTL cache of every outcome.

    Args:
        index_url: where the signed document lives.
        public_key_b64: the Ed25519 public key it must verify against.
        client: an ``httpx.AsyncClient`` to reuse (tests); one is created
            and owned otherwise.
        last_good_path: where the last *verified* document is kept.
        cache_dir: the TTL cache directory; defaults to
            ``<last_good_path's directory>/market_curated_cache`` so both
            live in the hub home, like ``registry_cache`` does.
        ttl_seconds: how long a verified fetch is served without a
            network round-trip.
        failure_ttl_seconds: how long a failed fetch is remembered
            before the URL is retried.
        clock: seconds-since-epoch time source; injectable so tests can
            expire the cache without sleeping.
    """

    def __init__(
        self,
        *,
        index_url: str = DEFAULT_INDEX_URL,
        public_key_b64: str = DEFAULT_PUBLIC_KEY_B64,
        client: httpx.AsyncClient | None = None,
        last_good_path: Path | None = None,
        cache_dir: Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        failure_ttl_seconds: float = DEFAULT_FAILURE_TTL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.index_url = index_url
        self.public_key_b64 = public_key_b64
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self.last_good_path = last_good_path or (palaia_home() / LAST_GOOD_RELATIVE_PATH)
        self._cache = DiskCache(cache_dir or (self.last_good_path.parent / CACHE_RELATIVE_PATH))
        self.ttl_seconds = ttl_seconds
        self.failure_ttl_seconds = failure_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self._clock = clock

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---------------------------------------------------------------- disk

    def _read_last_good(self) -> dict[str, Any] | None:
        try:
            data: Any = json.loads(self.last_good_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _write_last_good(self, document: dict[str, Any]) -> None:
        self.last_good_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.last_good_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document), encoding="utf-8")
        harden_file(tmp)  # SPEC-502: narrowed before it becomes the real file
        tmp.replace(self.last_good_path)
        harden_file(self.last_good_path)

    @property
    def _cache_key(self) -> str:
        # Keyed by URL *and* key: a config change to either must not be
        # answered from the previous trust anchor's outcome.
        return f"{self.index_url}#{self.public_key_b64}"

    def _remember(self, payload: dict[str, Any]) -> None:
        self._cache.set(self._cache_key, payload, fetched_at=self._clock())

    def _from_cache(self) -> CuratedIndexResult | None:
        """The answer the TTL cache allows without a network round-trip,
        or ``None`` when the URL has to be asked (again)."""
        cached = self._cache.get(self._cache_key)
        if cached is None or not isinstance(cached.payload, dict):
            return None
        age = self._clock() - cached.fetched_at
        outcome = cached.payload.get("outcome")
        if outcome == "verified" and age < self.ttl_seconds:
            last_good = self._read_last_good()
            if last_good is None or "entries" not in last_good:
                return None  # the copy the cache vouches for is gone — refetch
            return self._fresh_result(last_good)
        if outcome == "failed" and age < self.failure_ttl_seconds:
            warning = str(cached.payload.get("warning", "index unavailable"))
            return self._fallback_result(warning, log_level=logging.DEBUG)
        return None

    # ------------------------------------------------------------- results

    @staticmethod
    def _fresh_result(document: dict[str, Any]) -> CuratedIndexResult:
        entries = tuple(_entry_from_raw(e, provenance="curated") for e in document["entries"])
        return CuratedIndexResult(
            entries=entries, generated_at=str(document["generated_at"]), stale=False, warning=""
        )

    def _fallback_result(
        self, warning: str, *, log_level: int = logging.WARNING
    ) -> CuratedIndexResult:
        last_good = self._read_last_good()
        if last_good is None:
            try:
                last_good = load_starter_index()
                verify_index_document(
                    last_good, public_key_b64=self.public_key_b64, known_generated_at=None
                )
            except (FileNotFoundError, ModuleNotFoundError, IndexVerificationError):
                logger.log(
                    log_level,
                    "curated index unavailable, no last-verified copy and no usable "
                    "starter index: %s",
                    warning,
                )
                return CuratedIndexResult(entries=(), generated_at="", stale=True, warning=warning)
            logger.log(
                log_level,
                "curated index unavailable, serving the bundled starter index: %s",
                warning,
            )
        else:
            logger.log(
                log_level,
                "curated index refused/unreachable, serving last verified copy from %s: %s",
                last_good.get("generated_at", "?"),
                warning,
            )
        entries = tuple(_entry_from_raw(e, provenance="curated") for e in last_good["entries"])
        return CuratedIndexResult(
            entries=entries, generated_at=last_good["generated_at"], stale=True, warning=warning
        )

    # --------------------------------------------------------------- fetch

    async def _download(self) -> dict[str, Any]:
        try:
            response = await self._client.get(self.index_url, timeout=self.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise _FetchFailure(f"timed out after {self.timeout_seconds:.0f}s") from exc
        except httpx.RequestError as exc:
            raise _FetchFailure(f"network error: {exc}") from exc

        if response.status_code >= 400:
            raise _FetchFailure(f"index host answered HTTP {response.status_code}")
        if len(response.content) > self.max_bytes:
            raise _FetchFailure(
                f"index document too large ({len(response.content)} > {self.max_bytes} bytes)"
            )
        try:
            document = response.json()
        except ValueError as exc:
            raise _FetchFailure("index document is not valid JSON") from exc
        if not isinstance(document, dict):
            raise _FetchFailure("index document is not a JSON object")
        return document

    async def fetch(self, *, force: bool = False) -> CuratedIndexResult:
        """The curated index — from the TTL cache when it is fresh enough,
        otherwise fetched, verified and recorded.

        Args:
            force: ask the URL regardless of the cache (the explicit
                refresh path, :meth:`MarketService.refresh_curated_index`).
                The result still lands in the cache.
        """
        if not force:
            cached = self._from_cache()
            if cached is not None:
                return cached

        last_good = self._read_last_good()
        known_generated_at = str(last_good["generated_at"]) if last_good else None
        try:
            document = await self._download()
            verify_index_document(
                document, public_key_b64=self.public_key_b64, known_generated_at=known_generated_at
            )
        except _FetchFailure as exc:
            reason = exc.reason
        except IndexVerificationError as exc:
            logger.warning("refusing curated index from %s: %s", self.index_url, exc.reason)
            reason = exc.reason
        else:
            self._write_last_good(document)
            self._remember({"outcome": "verified", "generated_at": str(document["generated_at"])})
            return self._fresh_result(document)

        self._remember({"outcome": "failed", "warning": reason})
        return self._fallback_result(reason)


__all__ = [
    "CACHE_RELATIVE_PATH",
    "DEFAULT_FAILURE_TTL_SECONDS",
    "DEFAULT_INDEX_URL",
    "DEFAULT_PUBLIC_KEY_B64",
    "DEFAULT_TTL_SECONDS",
    "CuratedIndexClient",
    "CuratedIndexResult",
    "IndexVerificationError",
    "canonical_bytes",
    "verify_index_document",
]
