"""The curated palaia add-on index (SPEC-303 deliverable #2).

A **signed JSON document**, fixed shape::

    {schema_version, generated_at, entries: [...], signature}

fetched from a configurable URL and verified against a pinned Ed25519
public key baked into the package (never fetched, never configurable —
that would defeat the point). ``signature`` is a base64-encoded Ed25519
signature over the canonical JSON encoding (``json.dumps(..., sort_keys=
True, separators=(",", ":"))``) of the document *without* the
``signature`` key itself.

A tampered document — wrong signature, wrong (attacker's) key, or a
``generated_at`` older than the last copy we already trusted (a rollback/
downgrade attack) — is refused loudly (a WARNING naming the exact reason)
and this module falls back to the last verified copy on disk. When there
is no such copy, refusal means an empty curated index, never a
half-trusted document silently accepted.
"""

from __future__ import annotations

import base64
import importlib.resources
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..config import palaia_home
from .models import MarketEntry, SourceLocator

logger = logging.getLogger("palaia_hub.market.curated")

#: The pinned Ed25519 public key (raw 32 bytes, base64), baked into the
#: package. Generated for this repository's starter curated index; the
#: matching private key is deliberately NOT in the repo (see
#: ``v3/tools/README.md`` and ``v3/tools/sign_market_index.py``) — whoever
#: publishes the real palaia curated index controls it, and rotating it
#: means shipping a new pinned key here, not a config option (a
#: configurable trust anchor is not a trust anchor).
DEFAULT_PUBLIC_KEY_B64 = "xh8oKQEO/x7pfXrfqieqjkUc866ZcDPuCvkI3MhSN8k="

DEFAULT_INDEX_URL = "https://index.palaia.dev/market-index.json"
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
LAST_GOOD_RELATIVE_PATH = "market_curated_index.json"

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


class CuratedIndexClient:
    """Fetch + verify the curated index, with a signed-fallback-to-disk."""

    def __init__(
        self,
        *,
        index_url: str = DEFAULT_INDEX_URL,
        public_key_b64: str = DEFAULT_PUBLIC_KEY_B64,
        client: httpx.AsyncClient | None = None,
        last_good_path: Path | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.index_url = index_url
        self.public_key_b64 = public_key_b64
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self.last_good_path = last_good_path or (palaia_home() / LAST_GOOD_RELATIVE_PATH)
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

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
        tmp.replace(self.last_good_path)

    def _fallback_result(self, warning: str) -> CuratedIndexResult:
        last_good = self._read_last_good()
        if last_good is None:
            try:
                last_good = load_starter_index()
                verify_index_document(
                    last_good, public_key_b64=self.public_key_b64, known_generated_at=None
                )
            except (FileNotFoundError, ModuleNotFoundError, IndexVerificationError):
                logger.warning(
                    "curated index unavailable, no last-verified copy and no usable "
                    "starter index: %s",
                    warning,
                )
                return CuratedIndexResult(entries=(), generated_at="", stale=True, warning=warning)
            logger.warning(
                "curated index unavailable, serving the bundled starter index: %s", warning
            )
        else:
            logger.warning(
                "curated index refused/unreachable, serving last verified copy from %s: %s",
                last_good.get("generated_at", "?"),
                warning,
            )
        entries = tuple(_entry_from_raw(e, provenance="curated") for e in last_good["entries"])
        return CuratedIndexResult(
            entries=entries, generated_at=last_good["generated_at"], stale=True, warning=warning
        )

    async def fetch(self) -> CuratedIndexResult:
        try:
            response = await self._client.get(self.index_url, timeout=self.timeout_seconds)
        except httpx.TimeoutException:
            return self._fallback_result(f"timed out after {self.timeout_seconds:.0f}s")
        except httpx.RequestError as exc:
            return self._fallback_result(f"network error: {exc}")

        if response.status_code >= 400:
            return self._fallback_result(f"index host answered HTTP {response.status_code}")
        if len(response.content) > self.max_bytes:
            return self._fallback_result(
                f"index document too large ({len(response.content)} > {self.max_bytes} bytes)"
            )
        try:
            document = response.json()
        except ValueError:
            return self._fallback_result("index document is not valid JSON")
        if not isinstance(document, dict):
            return self._fallback_result("index document is not a JSON object")

        last_good = self._read_last_good()
        known_generated_at = str(last_good["generated_at"]) if last_good else None
        try:
            verify_index_document(
                document, public_key_b64=self.public_key_b64, known_generated_at=known_generated_at
            )
        except IndexVerificationError as exc:
            logger.warning("refusing curated index from %s: %s", self.index_url, exc.reason)
            return self._fallback_result(exc.reason)

        self._write_last_good(document)
        entries = tuple(_entry_from_raw(e, provenance="curated") for e in document["entries"])
        return CuratedIndexResult(
            entries=entries, generated_at=str(document["generated_at"]), stale=False, warning=""
        )


__all__ = [
    "DEFAULT_INDEX_URL",
    "DEFAULT_PUBLIC_KEY_B64",
    "CuratedIndexClient",
    "CuratedIndexResult",
    "IndexVerificationError",
    "canonical_bytes",
    "verify_index_document",
]
