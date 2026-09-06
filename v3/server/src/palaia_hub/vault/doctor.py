"""Doctor primitives: ``verify`` findings and the ``reindex`` hook points.

``verify`` is the file-side half of the file↔index consistency check; the
index side lands in SPEC-104 and plugs in through :class:`IndexView`, so the
drift checks below are already written against an interface rather than a
concrete database.

``reindex`` walks the vault and feeds every note to a :class:`ReindexSink` —
the hook SPEC-103/104 implement to rebuild the disposable index from files
alone. This module never parses note semantics; it hands sinks whole
:class:`~.models.Note` values.

Findings are advisory data, not exceptions: the doctor reports, the caller
(dashboard, CLI, curator) decides. :meth:`VaultDoctor.repair` performs only
the repairs the SPEC-003 findings proved safe and sufficient — clearing
stale git locks and sweeping crash-residue temp files.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from . import permalink as pl
from .atomic import TEMP_SUFFIX, sweep_temp_files
from .engine import VaultEngine
from .errors import AmbiguousReferenceError, NoteNotFoundError, VaultError
from .links import iter_links
from .models import MANIFEST_PATH, VAULT_FORMAT_VERSION, Note

logger = logging.getLogger("palaia_hub.vault.doctor")

Severity = Literal["info", "warning", "error"]

#: Format spec §1 layout guidance: keep directories under ~500 files, because
#: git's tree-object cost per commit scales with directory size (SPEC-003).
MAX_NOTES_PER_DIRECTORY = 500


@dataclass(frozen=True, slots=True)
class Finding:
    """One doctor observation about the vault."""

    code: str
    severity: Severity
    detail: str
    fix: str
    path: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """What the doctor needs to know about one row of the derived index."""

    permalink: str
    path: str
    checksum: str


@runtime_checkable
class IndexView(Protocol):
    """The SPEC-104 index, as far as file↔index verification is concerned."""

    def index_entries(self) -> Iterable[IndexEntry]:
        """Yield one entry per indexed note."""
        ...


@runtime_checkable
class ReindexSink(Protocol):
    """Receives every note of a vault during a reindex."""

    def begin(self, vault: str) -> None:
        """Called once before the first note."""
        ...

    def emit(self, note: Note) -> None:
        """Called once per note, in path order."""
        ...

    def finish(self) -> None:
        """Called once after the last note."""
        ...


class VaultDoctor:
    """Consistency checks and safe repairs for one vault."""

    def __init__(self, engine: VaultEngine) -> None:
        self.engine = engine

    async def verify(self, index: IndexView | None = None) -> list[Finding]:
        """Check the vault (and optionally the index) and report findings."""
        return await asyncio.to_thread(self._verify_sync, index)

    def _verify_sync(self, index: IndexView | None) -> list[Finding]:
        engine = self.engine
        findings: list[Finding] = []
        findings.extend(self._check_manifest())
        findings.extend(self._check_git())
        findings.extend(self._check_identity())
        findings.extend(self._check_encoding())
        findings.extend(self._check_links())
        findings.extend(self._check_directory_sizes())
        findings.extend(self._check_temp_files())
        if index is not None:
            findings.extend(self._check_index(index))
        logger.debug("doctor: %d finding(s) for vault %s", len(findings), engine.name)
        return findings

    # -------------------------------------------------------------- individual

    def _check_manifest(self) -> list[Finding]:
        path = self.engine.root / MANIFEST_PATH
        if not path.exists():
            return [
                Finding(
                    code="manifest-missing",
                    severity="warning",
                    detail=f"{MANIFEST_PATH} is missing; the vault is importable but not servable.",
                    fix="Re-open the vault with create=True to write the manifest.",
                    path=MANIFEST_PATH,
                )
            ]
        if not self.engine.writable:
            return [
                Finding(
                    code="format-version",
                    severity="error",
                    detail=(
                        f"{MANIFEST_PATH} declares vault_format "
                        f"{self.engine.info().format_version}; this engine writes "
                        f"{VAULT_FORMAT_VERSION}. Reads are best-effort, writes refused."
                    ),
                    fix="Upgrade palaia, or migrate the vault to a known format version.",
                    path=MANIFEST_PATH,
                )
            ]
        return []

    def _check_git(self) -> list[Finding]:
        engine = self.engine
        findings: list[Finding] = []
        if not engine.git.initialized:
            return [
                Finding(
                    code="git-missing",
                    severity="error",
                    detail=f"{engine.root} has no git repository, so there is no history.",
                    fix="Re-open the vault with create=True to initialize git.",
                )
            ]
        for recovery in engine.git.recover_stale_locks():
            if recovery.removed:
                findings.append(
                    Finding(
                        code="git-lock-stale",
                        severity="warning",
                        detail=(
                            f"stale {recovery.path} (age {recovery.age_seconds:.1f}s) was "
                            f"left behind by a crashed git operation and has been removed."
                        ),
                        fix="No action needed — removing the lock is sufficient repair.",
                    )
                )
            else:
                findings.append(
                    Finding(
                        code="git-lock-held",
                        severity="info",
                        detail=(
                            f"{recovery.path} exists and is only "
                            f"{recovery.age_seconds:.1f}s old — it may belong to a live "
                            f"external git process, so it was left in place."
                        ),
                        fix="Re-run the doctor; if it persists, stop other git clients.",
                    )
                )
        dirty = engine.git.dirty_paths()
        if dirty:
            findings.append(
                Finding(
                    code="uncommitted-changes",
                    severity="info",
                    detail=f"{len(dirty)} path(s) changed outside the engine and are uncommitted.",
                    fix="They are committed as a human-attributed commit on the next engine write.",
                )
            )
        content = engine.git.content_size_bytes()
        git_size = engine.git.size_bytes()
        if content > 0 and git_size > 3 * content:
            findings.append(
                Finding(
                    code="repo-bloat",
                    severity="warning",
                    detail=(
                        f".git is {git_size / 1e6:.1f} MB for {content / 1e6:.1f} MB of "
                        f"content ({git_size / content:.1f}x) — loose objects from "
                        f"one-commit-per-write have accumulated."
                    ),
                    fix="Run engine.gc() (git gc) — the spike recovered ~11x this way.",
                )
            )
        return findings

    def _check_identity(self) -> list[Finding]:
        findings: list[Finding] = []
        by_permalink: dict[str, list[str]] = {}
        for entry in self.engine.catalog.values():
            if not entry.permalink:
                findings.append(
                    Finding(
                        code="permalink-missing",
                        severity="warning",
                        detail=f"{entry.path} has no permalink, so it has no stable identity.",
                        fix="Run engine.assign_missing_permalinks() to mint one (§3.1).",
                        path=entry.path,
                    )
                )
                continue
            by_permalink.setdefault(entry.permalink, []).append(entry.path)
            if not pl.is_canonical(entry.permalink):
                findings.append(
                    Finding(
                        code="permalink-noncanonical",
                        severity="info",
                        detail=(
                            f"{entry.path} has permalink {entry.permalink!r}, which is outside "
                            f"the canonical charset. It is kept verbatim — identity is never "
                            f"silently rewritten."
                        ),
                        fix=(
                            "Canonicalize via rename_entity(), which keeps the old value "
                            "as an alias."
                        ),
                        path=entry.path,
                    )
                )
            for kind, value in (("title", entry.title), ("permalink", entry.permalink)):
                violations = pl.volatility_violations(value)
                if violations:
                    findings.append(
                        Finding(
                            code="volatile-name",
                            severity="warning",
                            detail=(
                                f"{entry.path}: {kind} {value!r} carries volatile data "
                                f"({', '.join(violations)}) — §4.1."
                            ),
                            fix=(
                                "rename_entity() to a stable name; record the value as "
                                "an observation."
                            ),
                            path=entry.path,
                        )
                    )
        for permalink, paths in by_permalink.items():
            if len(paths) > 1:
                findings.append(
                    Finding(
                        code="permalink-duplicate",
                        severity="error",
                        detail=(
                            f"permalink {permalink!r} is claimed by {len(paths)} notes: "
                            f"{', '.join(sorted(paths))}. Permalinks must be unique per vault."
                        ),
                        fix="rename_entity() all but one of them.",
                        path=sorted(paths)[0],
                    )
                )
        return findings

    def _check_encoding(self) -> list[Finding]:
        """Report notes whose bytes are not valid UTF-8 (issue #355).

        The engine reads them with replacement characters and refuses to
        edit them — this finding is where the owner learns why, and what to
        do about it.
        """
        findings: list[Finding] = []
        for path in sorted(self.engine.catalog):
            try:
                raw = (self.engine.root / path).read_bytes()
            except OSError:  # pragma: no cover - vanished under us
                continue
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                findings.append(
                    Finding(
                        code="not-utf8",
                        severity="warning",
                        detail=(
                            f"{path} is not valid UTF-8 (byte {exc.start}: {exc.reason}); "
                            "it is searchable with replacement characters but cannot be "
                            "edited through palaia until it is converted."
                        ),
                        fix=(
                            "Convert the file to UTF-8 with your editor, or "
                            "`iconv -f latin1 -t utf-8 <file> > <file>.utf8 && mv <file>.utf8 "
                            "<file>`."
                        ),
                        path=path,
                    )
                )
        return findings

    def _check_links(self) -> list[Finding]:
        """Report unresolvable wikilinks, flagging likely partial renames.

        A human renaming a note in Obsidian without rewriting backlinks (or
        an engine rename that raced an external edit) leaves links pointing at
        the old title. Those links still *identify* an entity — the one whose
        permalink ends in the target's slug — which is what distinguishes a
        partial rename from a plain forward reference to a note that simply
        does not exist yet (forward references are first-class, §5.2).
        """
        engine = self.engine
        findings: list[Finding] = []
        slug_index: dict[str, list[str]] = {}
        for entry in engine.catalog.values():
            if entry.permalink:
                slug_index.setdefault(entry.permalink.rsplit("/", 1)[-1], []).append(entry.path)

        for path in sorted(engine.catalog):
            try:
                raw = (engine.root / path).read_bytes()
            except OSError:  # pragma: no cover - vanished under us
                continue
            # Links are ASCII-delimited; a note that is not UTF-8 (reported
            # by `_check_encoding`) is still scanned rather than crashing
            # the whole verify (issue #355).
            text = raw.decode("utf-8", errors="replace")
            seen: set[str] = set()
            for link in iter_links(text):
                target = link.target
                if not target or target in seen:
                    continue
                seen.add(target)
                if self._resolves(target):
                    continue
                slug = pl.slugify(target)
                candidates = slug_index.get(slug, [])
                if candidates and all(candidate != path for candidate in candidates):
                    findings.append(
                        Finding(
                            code="partial-rename",
                            severity="warning",
                            detail=(
                                f"{path} links to [[{target}]], which no longer resolves, but "
                                f"{candidates[0]} still owns the matching permalink slug — "
                                f"an entity was renamed without rewriting its backlinks (§4.2)."
                            ),
                            fix=(
                                "rename_entity() rewrites all backlinks atomically; or add the "
                                "old name to that note's aliases."
                            ),
                            path=path,
                            line=link.line,
                        )
                    )
                    continue
                findings.append(
                    Finding(
                        code="dangling-link",
                        severity="info",
                        detail=(
                            f"{path} links to [[{target}]], which matches no note. Forward "
                            f"references are legal (§5.2) — this is a report, not an error."
                        ),
                        fix="Create the target note, or fix the link target.",
                        path=path,
                        line=link.line,
                    )
                )
        return findings

    def _resolves(self, target: str) -> bool:
        try:
            self.engine.resolve(target)
        except AmbiguousReferenceError:
            # Ambiguous is not dangling: the link does name existing notes.
            return True
        except VaultError:
            return False
        return True

    def _check_directory_sizes(self) -> list[Finding]:
        """Report directories past the format spec's size guidance (§1).

        Not cosmetic: git rewrites a directory's tree object on every commit
        touching it, so per-commit cost and repository growth scale with
        *directory* size. Measured on a 10k-note vault: one flat directory
        ends at ``.git`` 4.4x its content after gc, while the same notes
        sharded stay proportional.
        """
        counts: dict[str, int] = {}
        for path in self.engine.catalog:
            folder = path.rsplit("/", 1)[0] if "/" in path else "."
            counts[folder] = counts.get(folder, 0) + 1
        findings: list[Finding] = []
        for folder, count in sorted(counts.items()):
            if count <= MAX_NOTES_PER_DIRECTORY:
                continue
            findings.append(
                Finding(
                    code="directory-large",
                    severity="info",
                    detail=(
                        f"{folder} holds {count} notes, past the ~{MAX_NOTES_PER_DIRECTORY} "
                        f"guidance (§1). Git rewrites this directory's tree object on every "
                        f"commit that touches it, so both write latency and repository growth "
                        f"scale with the count."
                    ),
                    fix="Split the notes into topic subfolders (move_note keeps permalinks).",
                    path=folder,
                )
            )
        return findings

    def _check_temp_files(self) -> list[Finding]:
        leftovers = [path for path in self.engine.root.rglob(f"*{TEMP_SUFFIX}") if path.is_file()]
        if not leftovers:
            return []
        return [
            Finding(
                code="orphan-temp-file",
                severity="info",
                detail=(
                    f"{len(leftovers)} engine temp file(s) left over from a write that was "
                    f"interrupted before its atomic rename. The note itself is intact."
                ),
                fix="Run doctor.repair() (or re-open the vault) to sweep them.",
                path=str(leftovers[0].name),
            )
        ]

    def _check_index(self, index: IndexView) -> list[Finding]:
        findings: list[Finding] = []
        catalog = self.engine.catalog
        indexed: dict[str, IndexEntry] = {}
        for entry in index.index_entries():
            indexed[entry.path] = entry
            if entry.path not in catalog:
                findings.append(
                    Finding(
                        code="index-orphan-entry",
                        severity="warning",
                        detail=(
                            f"the index has {entry.permalink!r} at {entry.path}, but no such "
                            f"file exists. Files are the only truth."
                        ),
                        fix="Reindex the vault (the index is disposable).",
                        path=entry.path,
                    )
                )
                continue
            if catalog[entry.path].checksum != entry.checksum:
                findings.append(
                    Finding(
                        code="index-stale-entry",
                        severity="warning",
                        detail=f"index checksum for {entry.path} differs from the file on disk.",
                        fix="Reindex the vault (the index is disposable).",
                        path=entry.path,
                    )
                )
        for path in sorted(catalog):
            if path not in indexed:
                findings.append(
                    Finding(
                        code="index-missing-entry",
                        severity="warning",
                        detail=f"{path} exists on disk but is not in the index.",
                        fix="Reindex the vault (the index is disposable).",
                        path=path,
                    )
                )
        return findings

    # ----------------------------------------------------------------- repairs

    async def repair(self) -> list[Finding]:
        """Perform the safe repairs: stale git locks and orphaned temp files.

        SPEC-003 Q5: across 25 kill trials, removing a stale lock was the only
        repair ever needed and was always sufficient. Nothing here touches
        note content.
        """
        return await asyncio.to_thread(self._repair_sync)

    def _repair_sync(self) -> list[Finding]:
        findings: list[Finding] = []
        for recovery in self.engine.git.recover_stale_locks():
            findings.append(
                Finding(
                    code="git-lock-stale" if recovery.removed else "git-lock-held",
                    severity="warning" if recovery.removed else "info",
                    detail=(
                        f"{recovery.path} (age {recovery.age_seconds:.1f}s) "
                        f"{'removed' if recovery.removed else 'left in place'}."
                    ),
                    fix=(
                        "No action needed."
                        if recovery.removed
                        else "Stop other git clients and retry."
                    ),
                )
            )
        for path in sweep_temp_files(self.engine.root):
            findings.append(
                Finding(
                    code="orphan-temp-file",
                    severity="info",
                    detail=f"swept leftover temp file {path.name}.",
                    fix="No action needed.",
                    path=path.name,
                )
            )
        return findings

    # ---------------------------------------------------------------- reindex

    async def reindex(self, sink: ReindexSink) -> int:
        """Feed every note in the vault to ``sink``; return the note count.

        The rebuild-from-files path SPEC-104's "index is disposable" acceptance
        criterion depends on: notes are read from disk (never from the
        catalog's cached state) in stable path order.

        The catalog rebuild goes through :meth:`VaultEngine.refresh`, which
        holds the engine's write lock — a rebuild never races a write that is
        landing at the same moment (issue #331). The walk itself then reads a
        published snapshot, so it cannot observe a half-applied catalog.
        """
        await self.engine.refresh()
        return await asyncio.to_thread(self._reindex_sync, sink)

    def _reindex_sync(self, sink: ReindexSink) -> int:
        engine = self.engine
        sink.begin(engine.name)
        count = 0
        try:
            for path in sorted(engine.catalog):
                try:
                    note = engine.read_note_at(path)
                except NoteNotFoundError:
                    # Deleted between the catalog snapshot and this read: the
                    # delete's own event removes it from the index (#332).
                    continue
                sink.emit(note)
                count += 1
        except BaseException:
            # A sink that can roll back gets the chance to — a half-built
            # index must never be committed by whoever writes next (#332).
            abort = getattr(sink, "abort", None)
            if callable(abort):
                abort()
            raise
        sink.finish()
        return count


def summarize(findings: Iterable[Finding]) -> dict[str, int]:
    """Count findings per code — handy for logs, the dashboard and tests."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return counts


__all__ = [
    "Finding",
    "IndexEntry",
    "IndexView",
    "ReindexSink",
    "Severity",
    "VaultDoctor",
    "summarize",
]
