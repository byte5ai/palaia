"""The hook store: outbound webhook configuration (SPEC-201 deliverable #3).

Persisted as ``hooks.yaml`` under the hub's home directory — same directory,
same atomic-write primitive, and the same shape of module as
:class:`palaia_hub.auth.store.TokenStore` and
:class:`palaia_hub.vault.registry.VaultRegistry`. Unlike a client token, a
hook's ``secret`` is stored as plain text (see :class:`~.models.HookRecord`'s
docstring for why) — it never leaves this file except inside the one
``POST``/create response, and it must never reach a log line (see
:mod:`palaia_hub.logging`'s redaction filter, which also catches a
``secret=...``-shaped mention as a second line of defense).
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import palaia_home
from ..security.files import harden_directory, harden_file
from ..vault.atomic import atomic_write_text
from .models import CreatedHook, HookInfo, HookRecord

logger = logging.getLogger("palaia_hub.hooks.store")

HOOKS_FILE = "hooks.yaml"

_HEADER = (
    "# palaia outbound webhooks — see v3/docs/events.md for the event schema.\n"
    "# 'secret' signs every delivery (HMAC-SHA256); never share it or commit\n"
    "# this file to a public repo.\n"
)


class HookError(RuntimeError):
    """Raised for a caller-facing hook-store failure (bad url, no such id)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class HookStore:
    """Create, list, enable/disable, and delete outbound webhooks.

    Args:
        home: directory holding ``hooks.yaml``. Defaults to the hub's data
            directory (``PALAIA_HOME`` or the platform data dir), mirroring
            :class:`palaia_hub.auth.store.TokenStore`.
    """

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else palaia_home()
        self._records: dict[str, HookRecord] = {}
        self._load()

    @property
    def store_path(self) -> Path:
        """Path to ``hooks.yaml``."""
        return self.home / HOOKS_FILE

    # ------------------------------------------------------------- persistence

    def _load(self) -> None:
        path = self.store_path
        if not path.exists():
            return
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise HookError(
                f"{path}: could not parse YAML ({exc}). Fix: correct the syntax, or "
                f"delete the file to start with no hooks configured."
            ) from exc
        if not raw:
            return
        if not isinstance(raw, Mapping) or not isinstance(raw.get("hooks"), list):
            raise HookError(
                f"{path}: expected a 'hooks:' list of records. Fix: correct the "
                f"file, or delete it to start over."
            )
        for item in raw["hooks"]:
            record = HookRecord.model_validate(item)
            self._records[record.id] = record

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {"hooks": [r.model_dump(mode="json") for r in self._records.values()]}
        text = _HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        atomic_write_text(self.store_path, text)
        # SPEC-502: one shared rule for every persisted file, rather than a
        # literal mode repeated per store.
        harden_file(self.store_path)
        harden_directory(self.home)

    # ----------------------------------------------------------------- queries

    def list_hooks(self, *, enabled_only: bool = False) -> list[HookRecord]:
        """Every hook, in creation order, records included (delivery needs the secret)."""
        records = list(self._records.values())
        if enabled_only:
            records = [r for r in records if r.enabled]
        return records

    def list_info(self) -> list[HookInfo]:
        """The secret-free view — what the REST surface lists."""
        return [HookInfo.from_record(r) for r in self._records.values()]

    def get(self, hook_id: str) -> HookRecord | None:
        return self._records.get(hook_id)

    # ------------------------------------------------------------- mutations

    def create(self, url: str, events: Sequence[str] | None = None) -> CreatedHook:
        """Register a new webhook; returns its info plus the plaintext secret once."""
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            raise HookError(
                f"hook url {url!r} must be an absolute http(s) URL. "
                f"Fix: pass a full URL such as 'https://example.com/hooks/palaia'."
            )
        hook_id = secrets.token_urlsafe(9)
        secret = secrets.token_urlsafe(32)
        record = HookRecord(
            id=hook_id,
            url=url,
            events=list(events) if events else ["*"],
            secret=secret,
            enabled=True,
            created_at=_now(),
        )
        self._records[hook_id] = record
        self._save()
        logger.info("created hook %s -> %s (events=%r)", hook_id, url, record.events)
        return CreatedHook(info=HookInfo.from_record(record), secret=secret)

    def set_enabled(self, hook_id: str, enabled: bool) -> HookInfo:
        record = self._records.get(hook_id)
        if record is None:
            raise HookError(f"no hook with id {hook_id!r}. Fix: check the id with list_info().")
        updated = record.model_copy(update={"enabled": enabled})
        self._records[hook_id] = updated
        self._save()
        logger.info("hook %s %s", hook_id, "enabled" if enabled else "disabled")
        return HookInfo.from_record(updated)

    def delete(self, hook_id: str) -> None:
        if self._records.pop(hook_id, None) is None:
            raise HookError(f"no hook with id {hook_id!r}. Fix: check the id with list_info().")
        self._save()
        logger.info("deleted hook %s", hook_id)


__all__ = ["HOOKS_FILE", "HookError", "HookStore"]
