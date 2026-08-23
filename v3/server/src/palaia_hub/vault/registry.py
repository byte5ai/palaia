"""Vault registry: many vaults, physically isolated.

MASTERPLAN §5.1: "one vault or many — the user's choice … isolation between
vaults is physical, not conventional". This registry enforces exactly that.
Each vault is a self-contained directory with its own notes, its own git
history and its own ``.palaia/`` engine storage; the registry only records
*where* they are (``vaults.yaml`` under the hub's home directory) and refuses
registrations that would let two vaults share storage — duplicate paths and
nested vault roots.

Names and purposes are read from each vault's own manifest (§1.2), so the
registry file stays a pointer list and the vault itself remains the truth.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .atomic import atomic_write_text
from .engine import VaultEngine
from .errors import VaultConfigError, VaultNotFoundError
from .events import EventBus
from .gitlayer import DEFAULT_POLICY, GitPolicy
from .models import Attribution, VaultInfo

logger = logging.getLogger("palaia_hub.vault.registry")

REGISTRY_FILE = "vaults.yaml"

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

_HEADER = (
    "# palaia vault registry — which vaults this hub serves and where they live.\n"
    "# Each vault is physically isolated: its own files, git history and index.\n"
    "# Names and purposes live in each vault's meta/vault.md manifest.\n"
)


@dataclass(frozen=True, slots=True)
class VaultRecord:
    """One registry row: a vault's name and its root directory."""

    name: str
    path: Path

    def as_dict(self) -> dict[str, str]:
        """Serialize for ``vaults.yaml``."""
        return {"name": self.name, "path": str(self.path)}


class VaultRegistry:
    """Tracks the hub's vaults and hands out opened engines."""

    def __init__(
        self,
        home: Path,
        *,
        bus: EventBus | None = None,
        policy: GitPolicy = DEFAULT_POLICY,
    ) -> None:
        self.home = Path(home).expanduser()
        self.bus = bus
        self.policy = policy
        self._records: dict[str, VaultRecord] = {}
        self._engines: dict[str, VaultEngine] = {}
        self._load()

    # ------------------------------------------------------------- persistence

    @property
    def registry_path(self) -> Path:
        """Path to ``vaults.yaml``."""
        return self.home / REGISTRY_FILE

    def _load(self) -> None:
        path = self.registry_path
        if not path.exists():
            return
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise VaultConfigError(
                f"{path}: could not parse YAML ({exc}). Fix: correct the syntax, or "
                f"delete the file to start with no registered vaults."
            ) from exc
        if not raw:
            return
        if not isinstance(raw, Mapping) or not isinstance(raw.get("vaults"), list):
            raise VaultConfigError(
                f"{path}: expected a 'vaults:' list of {{name, path}} entries. "
                f"Fix: correct the file, or delete it to start over."
            )
        for item in raw["vaults"]:
            if not isinstance(item, Mapping) or "name" not in item or "path" not in item:
                raise VaultConfigError(
                    f"{path}: every vault entry needs a 'name' and a 'path'. "
                    f"Offending entry: {item!r}."
                )
            name = str(item["name"])
            self._validate_name(name)
            self._records[name] = VaultRecord(name=name, path=Path(str(item["path"])))

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {"vaults": [record.as_dict() for record in self._records.values()]}
        text = _HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        atomic_write_text(self.registry_path, text)

    # -------------------------------------------------------------- validation

    @staticmethod
    def _validate_name(name: str) -> None:
        if not NAME_RE.match(name):
            raise VaultConfigError(
                f"vault name {name!r} is invalid. Fix: use 1-32 characters of "
                f"[a-z0-9-], starting with a letter or digit (it becomes the "
                f"vault's MCP tool-family name)."
            )

    def _validate_isolation(self, name: str, path: Path) -> None:
        resolved = path.expanduser().resolve()
        for record in self._records.values():
            if record.name == name:
                continue
            other = record.path.expanduser().resolve()
            if other == resolved:
                raise VaultConfigError(
                    f"vault {name!r} would share its directory with {record.name!r} "
                    f"({resolved}). Fix: give each vault its own directory — isolation "
                    f"is physical, not conventional."
                )
            if _is_relative_to(resolved, other) or _is_relative_to(other, resolved):
                raise VaultConfigError(
                    f"vault {name!r} at {resolved} is nested with {record.name!r} at "
                    f"{other}. Fix: use sibling directories so notes, git history and "
                    f"index storage can never overlap."
                )

    # ----------------------------------------------------------------- queries

    def records(self) -> list[VaultRecord]:
        """Every registered vault, in registration order."""
        return list(self._records.values())

    def names(self) -> list[str]:
        """The names of every registered vault."""
        return list(self._records)

    def __contains__(self, name: object) -> bool:
        return name in self._records

    def __iter__(self) -> Iterator[VaultRecord]:
        return iter(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

    # ------------------------------------------------------------- mutations

    async def create(
        self,
        name: str,
        path: Path,
        *,
        purpose: str | None = None,
        attribution: Attribution | None = None,
    ) -> VaultEngine:
        """Register a new vault and initialize it on disk."""
        return await self._add(name, path, purpose=purpose, create=True, attribution=attribution)

    async def register(self, name: str, path: Path) -> VaultEngine:
        """Register an existing vault directory without initializing it."""
        return await self._add(name, path, purpose=None, create=False, attribution=None)

    async def _add(
        self,
        name: str,
        path: Path,
        *,
        purpose: str | None,
        create: bool,
        attribution: Attribution | None,
    ) -> VaultEngine:
        self._validate_name(name)
        if name in self._records:
            raise VaultConfigError(
                f"vault {name!r} is already registered at {self._records[name].path}. "
                f"Fix: pick another name, or unregister the existing entry first."
            )
        resolved = path.expanduser()
        self._validate_isolation(name, resolved)
        engine = VaultEngine(resolved, name, bus=self.bus, policy=self.policy)
        if attribution is None:
            await engine.open(purpose=purpose, create=create)
        else:
            await engine.open(purpose=purpose, create=create, attribution=attribution)
        self._records[name] = VaultRecord(name=name, path=resolved)
        self._engines[name] = engine
        self._save()
        logger.info("registered vault %s at %s", name, resolved)
        return engine

    async def get(self, name: str) -> VaultEngine:
        """Return the opened engine for ``name``, opening it on first use."""
        engine = self._engines.get(name)
        if engine is not None:
            return engine
        record = self._records.get(name)
        if record is None:
            known = ", ".join(sorted(self._records)) or "none"
            raise VaultNotFoundError(
                f"no vault named {name!r} is registered (known vaults: {known}). "
                f"Fix: register it with the registry's create()/register()."
            )
        engine = VaultEngine(record.path, name, bus=self.bus, policy=self.policy)
        await engine.open(create=False)
        self._engines[name] = engine
        return engine

    def unregister(self, name: str) -> VaultRecord:
        """Forget a vault. Its files are never touched."""
        record = self._records.pop(name, None)
        if record is None:
            raise VaultNotFoundError(
                f"no vault named {name!r} is registered. Fix: check the name with names()."
            )
        self._engines.pop(name, None)
        self._save()
        logger.info("unregistered vault %s (files at %s were kept)", name, record.path)
        return record

    async def info(self) -> list[VaultInfo]:
        """Return the manifest-backed info of every registered vault."""
        out: list[VaultInfo] = []
        for name in list(self._records):
            engine = await self.get(name)
            out.append(engine.info())
        return out

    async def aclose(self) -> None:
        """Close every opened engine."""
        for engine in list(self._engines.values()):
            await engine.close()
        self._engines.clear()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True
