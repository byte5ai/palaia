"""Shared value types for the v2 and basic-memory importers.

Both source readers (:mod:`.v2_source`, :mod:`.basic_memory_source`) produce
the same two outcomes for every source item: a :class:`MappedNote` ready to
write, or a :class:`SkippedItem` naming a reason a human can act on. Neither
type does any I/O; :class:`~palaia_hub.importers.runner.ImportRunner` is
what actually talks to the vault engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class MappedNote:
    """One source item, fully mapped to a v3 note — ready to write.

    ``permalink`` is minted deterministically from the source's own stable
    identity (never from title/content), so re-running an import against an
    unchanged source always proposes the same permalink — the basis of
    idempotence (:class:`~palaia_hub.importers.runner.ImportRunner` skips a
    permalink that already exists in the vault).
    """

    source_path: str
    permalink: str
    title: str
    body: str
    frontmatter: dict[str, Any]
    #: One-line human-readable description of what this item is, for reports.
    describe: str


@dataclass(frozen=True, slots=True)
class SkippedItem:
    """A source item that could not be mapped, with an actionable reason."""

    source_path: str
    reason: str


ImportOutcome = Literal["created", "already-imported", "skipped"]


@dataclass(frozen=True, slots=True)
class ImportedItem:
    """One item's outcome, for the report (apply mode carries a commit sha)."""

    source_path: str
    permalink: str
    outcome: ImportOutcome
    detail: str = ""
    commit: str | None = None


@dataclass(slots=True)
class ImportReport:
    """The result of one import run — dry-run or apply.

    Acceptance criterion: "dry-run report lists counts + every unmappable
    item with a reason". ``items`` is a fixed record of every source item
    considered, in source order, so the counts are always derivable from it
    (and are computed via the properties below rather than duplicated).
    """

    source: str
    source_path: str
    dry_run: bool
    items: list[ImportedItem] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)

    @property
    def created_count(self) -> int:
        return sum(1 for item in self.items if item.outcome == "created")

    @property
    def already_imported_count(self) -> int:
        return sum(1 for item in self.items if item.outcome == "already-imported")

    @property
    def unmappable_count(self) -> int:
        return len(self.skipped)

    @property
    def total_count(self) -> int:
        return len(self.items) + len(self.skipped)

    def summary(self) -> str:
        mode = "would create" if self.dry_run else "created"
        lines = [
            f"import {self.source} from {self.source_path} "
            f"({'dry-run' if self.dry_run else 'apply'}):",
            f"  {mode}: {self.created_count}",
            f"  already imported (skipped, idempotent): {self.already_imported_count}",
            f"  unmappable: {self.unmappable_count}",
            f"  total considered: {self.total_count}",
        ]
        if self.skipped:
            lines.append("unmappable items:")
            for item in self.skipped:
                lines.append(f"  - {item.source_path}: {item.reason}")
        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_path": self.source_path,
            "dry_run": self.dry_run,
            "created": self.created_count,
            "already_imported": self.already_imported_count,
            "unmappable": self.unmappable_count,
            "total": self.total_count,
            "items": [
                {
                    "source_path": item.source_path,
                    "permalink": item.permalink,
                    "outcome": item.outcome,
                    "detail": item.detail,
                    "commit": item.commit,
                }
                for item in self.items
            ],
            "skipped": [
                {"source_path": item.source_path, "reason": item.reason}
                for item in self.skipped
            ],
        }
