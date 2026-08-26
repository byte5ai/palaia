"""On-disk TTL cache for registry responses (SPEC-303 deliverable #1).

One JSON file per cache key under the hub's data directory. Deliberately
tiny — this is not the vault/index's storage layer, just "the hub must
browse the registry fine on a flaky connection and say 'cached N hours
ago'" made concrete: every read returns both the payload and its age, so a
caller can decide whether "old but present" is still useful, exactly like
:mod:`palaia_hub.stash.store` does for the stash tool family.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..security.files import harden_directory, harden_file


@dataclass(frozen=True, slots=True)
class CacheEntry:
    payload: Any
    fetched_at: float

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.fetched_at)


class DiskCache:
    """A flat directory of ``<sha256(key)>.json`` files."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        harden_directory(self.cache_dir)

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            envelope = json.loads(raw)
            return CacheEntry(payload=envelope["payload"], fetched_at=float(envelope["fetched_at"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            # A corrupt cache file is treated as absent, never a crash.
            return None

    def set(self, key: str, payload: Any, *, fetched_at: float | None = None) -> None:
        path = self._path(key)
        envelope = {
            "payload": payload,
            "fetched_at": fetched_at if fetched_at is not None else time.time(),
        }
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(envelope), encoding="utf-8")
        harden_file(tmp_path)  # SPEC-502: narrowed before it becomes the real file
        tmp_path.replace(path)
        harden_file(path)


__all__ = ["CacheEntry", "DiskCache"]
