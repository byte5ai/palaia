"""Bookkeeping for what the marketplace has installed (SPEC-304 #1/#4).

One JSON file, one record per installed add-on — deliberately not a
second source of truth for *whether* an add-on is mounted (that is
:class:`~palaia_hub.upstream.service.UpstreamService`'s job, keyed the
same way); this store only remembers what an
:class:`~palaia_hub.upstream.models.UpstreamConfig` alone cannot: which
marketplace entry it came from, what its ``source`` looked like at
install time (to detect "the curated index now lists a newer image" —
deliverable #4's update surface), and — for a container — the deterministic
name its ``docker run`` was given, so uninstall can remove it by name even
if the upstream registry entry is already gone.

Same atomic-write pattern as
:meth:`palaia_hub.market.curated.CuratedIndexClient._write_last_good`:
write to a sibling temp file, then ``rename`` over the real path, so a
crash mid-write never leaves a half-written file behind.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import palaia_home
from ..security.files import harden_file

INSTALLED_RELATIVE_PATH = "market_installed.json"


@dataclass(frozen=True, slots=True)
class InstalledAddonRecord:
    """One installed marketplace entry."""

    upstream_key: str
    entry_id: str
    name: str
    kind: str
    provenance: str
    #: The entry's ``source.value`` at install time (an image ref, a
    #: registry id, or a url) — compared against the *current* entry on
    #: every ``GET /api/market/installed`` to decide ``update_available``.
    installed_ref: str
    #: The image reference actually pulled, for a container install —
    #: ``None`` for every other kind.
    image: str | None
    #: The deterministic ``docker run --name`` this container was given —
    #: ``None`` for every other kind. Used by uninstall/update to remove a
    #: container even after its upstream registry entry is already gone.
    container_name: str | None
    installed_at: float
    #: The resolved container plan (issue #344): the bind mounts
    #: (``{config field: host path}``) and the plain environment the
    #: ``docker run`` was built with. A one-click update rebuilds the run
    #: command from these, so it keeps the add-on's mounts and settings
    #: instead of starting a bare container. Empty for other kinds and for
    #: records written before this field existed (see ``install.update``
    #: for how those recover them).
    mounts: dict[str, str] = field(default_factory=dict)
    plain_env: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "upstream_key": self.upstream_key,
            "entry_id": self.entry_id,
            "name": self.name,
            "kind": self.kind,
            "provenance": self.provenance,
            "installed_ref": self.installed_ref,
            "image": self.image,
            "container_name": self.container_name,
            "installed_at": self.installed_at,
            "mounts": dict(self.mounts),
            "plain_env": dict(self.plain_env),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> InstalledAddonRecord:
        return cls(
            upstream_key=data["upstream_key"],
            entry_id=data["entry_id"],
            name=data["name"],
            kind=data["kind"],
            provenance=data["provenance"],
            installed_ref=data["installed_ref"],
            image=data.get("image"),
            container_name=data.get("container_name"),
            installed_at=data["installed_at"],
            mounts={str(k): str(v) for k, v in (data.get("mounts") or {}).items()},
            plain_env={str(k): str(v) for k, v in (data.get("plain_env") or {}).items()},
        )


class InstalledAddonStore:
    """CRUD for :class:`InstalledAddonRecord`, keyed by ``upstream_key``."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (palaia_home() / INSTALLED_RELATIVE_PATH)
        self._lock = threading.Lock()

    def _read_all(self) -> dict[str, dict[str, Any]]:
        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_all(self, records: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records), encoding="utf-8")
        # SPEC-502: narrow the temp file *before* it becomes the real one,
        # so there is no window in which the record set is world-readable.
        harden_file(tmp)
        tmp.replace(self.path)
        harden_file(self.path)

    def put(self, record: InstalledAddonRecord) -> None:
        with self._lock:
            records = self._read_all()
            records[record.upstream_key] = record.to_json()
            self._write_all(records)

    def get(self, upstream_key: str) -> InstalledAddonRecord | None:
        with self._lock:
            raw = self._read_all().get(upstream_key)
        return InstalledAddonRecord.from_json(raw) if raw is not None else None

    def list(self) -> list[InstalledAddonRecord]:
        with self._lock:
            records = self._read_all()
        return [InstalledAddonRecord.from_json(records[key]) for key in sorted(records)]

    def delete(self, upstream_key: str) -> bool:
        with self._lock:
            records = self._read_all()
            if upstream_key not in records:
                return False
            del records[upstream_key]
            self._write_all(records)
        return True


__all__ = ["INSTALLED_RELATIVE_PATH", "InstalledAddonRecord", "InstalledAddonStore"]
