"""The vault engine: files are the only truth.

Every mutating call here is **synchronous write-through**: it returns only
after the note's bytes and its directory entry are on disk (tmp + fsync +
atomic rename, see :mod:`.atomic`) and the change is a git commit. There is
no accepted-but-unwritten state and no background materialization — the
explicit anti-goal from MASTERPLAN §5.1. The one failure between those two
steps — the files are written, the commit is refused (another git process
holds the index lock) — raises :class:`~.errors.UncommittedWriteError`, still
publishes the change events, and is committed by the next successful
operation or a retry of the same write (issue #333).

Identity lives in the permalink, never in the filename (format spec §3.1):
:meth:`VaultEngine.move_note` keeps a note's permalink, and only
:meth:`VaultEngine.rename_entity` mints a new one — atomically, with aliases
and vault-wide backlink rewriting in a single commit (§4.2).

Note *semantics* — observations, relations, embeds, the warning taxonomy —
are SPEC-103's. This module reads frontmatter as raw YAML for the identity
keys it owns and treats the body as opaque text, except for wikilink target
rewriting during a rename.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar, cast

from . import frontmatter as fm
from . import permalink as pl
from .atomic import (
    TEMP_SUFFIX,
    atomic_move,
    atomic_write_text,
    durable_unlink,
    sha256_bytes,
    sweep_temp_files,
)
from .errors import (
    AmbiguousReferenceError,
    ChecksumConflictError,
    GitError,
    InvalidPathError,
    MalformedFrontmatterError,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    UncommittedWriteError,
    VaultError,
    VaultFormatVersionError,
    VaultNotFoundError,
    VolatileNameError,
)
from .events import (
    ChangeEvent,
    EntityRenamed,
    EventBus,
    NoteCreated,
    NoteDeleted,
    NoteModified,
    NoteMoved,
)
from .gitlayer import DEFAULT_POLICY, GitPolicy, GitRepo, LockRecovery
from .links import rewrite_targets
from .models import (
    ENGINE,
    HUMAN,
    IGNORED_DIRS,
    MANIFEST_PATH,
    NOTE_SUFFIX,
    RESERVED_DIRS,
    VAULT_FORMAT_VERSION,
    Attribution,
    CommitInfo,
    DirEntry,
    Note,
    Operation,
    RenameResult,
    VaultInfo,
    WriteResult,
    build_commit_message,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle: doctor builds on the engine
    from .doctor import Finding, IndexView, ReindexSink

logger = logging.getLogger("palaia_hub.vault.engine")

T = TypeVar("T")

MEMORY_SCHEME = "memory://"

GITIGNORE_BLOCK = (
    "# palaia engine-private storage: rebuildable index/state, never vault content\n"
    ".palaia/\n"
    "# in-flight atomic writes\n"
    f"*{TEMP_SUFFIX}\n"
)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """The engine's in-memory record of one note file.

    This is *not* the SPEC-104 index — it is a disposable identity catalog
    (path, permalink, title, aliases, checksum) the engine needs to keep
    permalinks unique, resolve references and rewrite backlinks. It is
    rebuilt from files by :meth:`VaultEngine.refresh`.
    """

    path: str
    permalink: str | None
    title: str
    aliases: tuple[str, ...]
    checksum: str
    size: int
    mtime_ns: int


class _Lookups:
    """Resolution tables over the catalog, maintained incrementally.

    Rebuilding these per write would make every write O(vault size) — the
    same shape of mistake as staging the whole git index per commit, so they
    are updated entry by entry instead.

    Title matches are tuples, never lists: a published
    :class:`_CatalogSnapshot` shares them with the writer's own copy, so
    nothing here is ever mutated in place once shared — :meth:`copy` can stay
    shallow for exactly that reason.
    """

    __slots__ = ("by_alias", "by_permalink", "by_title")

    def __init__(
        self,
        by_permalink: dict[str, str] | None = None,
        by_alias: dict[str, str] | None = None,
        by_title: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.by_permalink: dict[str, str] = {} if by_permalink is None else by_permalink
        self.by_alias: dict[str, str] = {} if by_alias is None else by_alias
        self.by_title: dict[str, tuple[str, ...]] = {} if by_title is None else by_title

    @property
    def permalinks(self) -> Mapping[str, str]:
        """Every claimed permalink, mapped to the path claiming it."""
        return self.by_permalink

    def copy(self) -> _Lookups:
        """An independent copy the writer may keep mutating."""
        return _Lookups(dict(self.by_permalink), dict(self.by_alias), dict(self.by_title))

    def add(self, entry: CatalogEntry) -> None:
        """Register one catalog entry. First claim of a key wins."""
        if entry.permalink:
            self.by_permalink.setdefault(entry.permalink, entry.path)
        for alias in entry.aliases:
            self.by_alias.setdefault(alias.lower(), entry.path)
        key = entry.title.lower()
        paths = self.by_title.get(key, ())
        if entry.path not in paths:
            self.by_title[key] = (*paths, entry.path)

    def remove(self, entry: CatalogEntry) -> None:
        """Unregister one catalog entry, keeping other notes' claims intact."""
        if entry.permalink and self.by_permalink.get(entry.permalink) == entry.path:
            del self.by_permalink[entry.permalink]
        for alias in entry.aliases:
            if self.by_alias.get(alias.lower()) == entry.path:
                del self.by_alias[alias.lower()]
        key = entry.title.lower()
        paths = self.by_title.get(key)
        if paths and entry.path in paths:
            remaining = tuple(path for path in paths if path != entry.path)
            if remaining:
                self.by_title[key] = remaining
            else:
                del self.by_title[key]


@dataclass(frozen=True, slots=True)
class _CatalogSnapshot:
    """What readers see of the catalog: one immutable, self-consistent view.

    The catalog is read from the event-loop thread (:meth:`VaultEngine.resolve`
    ahead of every edit, the gateway's listings, the dashboard) and from
    worker threads of their own (the doctor, the curator, an index rebuild)
    while *other* worker threads write it under the engine lock. Readers never
    touch the writer's dicts: they take the current snapshot — one attribute
    read, atomic under the interpreter — and work on that. A writer publishes
    a fresh snapshot once its operation is done, so a reader sees the state
    before an operation or the state after it, never a half-applied one, and
    iterating a snapshot can never raise "dictionary changed size during
    iteration" (issue #331).
    """

    entries: Mapping[str, CatalogEntry]
    lookups: _Lookups


_EMPTY_SNAPSHOT = _CatalogSnapshot(MappingProxyType({}), _Lookups())


class VaultEngine:
    """One vault: files, atomic writes, git history, identity.

    Args:
        root: the vault root directory.
        name: the vault's name (also its manifest ``name`` and tool-family
            name at the gateway).
        bus: optional event bus the engine publishes change events on.
        policy: git housekeeping policy (gc, stale-lock threshold).
        commit_external_edits: commit changes made outside the engine as
            their own ``human`` commit before the next engine write
            (format spec §10). Disable only in tests.
    """

    def __init__(
        self,
        root: Path,
        name: str = "default",
        *,
        bus: EventBus | None = None,
        policy: GitPolicy = DEFAULT_POLICY,
        commit_external_edits: bool = True,
    ) -> None:
        self.root = Path(root).expanduser()
        self.name = name
        self.bus = bus
        self.git = GitRepo(self.root, policy)
        self.commit_external_edits = commit_external_edits
        self._lock = asyncio.Lock()
        # The writer's copy of the catalog: touched only under `_lock`, on a
        # worker thread. Everyone else reads `_snapshot` (see _CatalogSnapshot).
        self._entries: dict[str, CatalogEntry] = {}
        self._tables = _Lookups()
        self._snapshot: _CatalogSnapshot = _EMPTY_SNAPSHOT
        self._deferring_publish = False
        # Writes that reached disk but whose commit failed (issue #333):
        # path -> (message, attribution), committed at the next opportunity.
        self._uncommitted: dict[str, tuple[str, Attribution]] = {}
        self._opened = False
        self._purpose: str | None = None
        self._format_version = VAULT_FORMAT_VERSION
        self._writable = True

    # ------------------------------------------------------------- properties

    @property
    def opened(self) -> bool:
        """True once :meth:`open` has run."""
        return self._opened

    @property
    def writable(self) -> bool:
        """False when the manifest declares an unknown format version (§1.1)."""
        return self._writable

    @property
    def engine_dir(self) -> Path:
        """The vault's engine-private directory (``.palaia/``)."""
        return self.root / ".palaia"

    def info(self) -> VaultInfo:
        """Return the vault's identity and size."""
        return VaultInfo(
            name=self.name,
            path=str(self.root),
            purpose=self._purpose,
            format_version=self._format_version,
            writable=self._writable,
            note_count=len(self._snapshot.entries),
        )

    # ---------------------------------------------------------------- lifecycle

    async def open(
        self,
        *,
        purpose: str | None = None,
        create: bool = True,
        attribution: Attribution = ENGINE,
    ) -> VaultInfo:
        """Open (and, with ``create``, initialize) the vault.

        Startup does the crash recovery the SPEC-003 kill test proved
        necessary: sweep orphaned temp files and clear stale git locks before
        anything else touches the repository.
        """
        async with self._lock:
            info = await asyncio.to_thread(self._open_sync, purpose, create, attribution)
        return info

    def _open_sync(self, purpose: str | None, create: bool, attribution: Attribution) -> VaultInfo:
        if not self.root.exists():
            if not create:
                raise VaultNotFoundError(
                    f"vault directory {self.root} does not exist. "
                    f"Fix: create it, or register the vault with create=True."
                )
            self.root.mkdir(parents=True, exist_ok=True)

        swept = sweep_temp_files(self.root)
        if swept:
            logger.info("swept %d orphaned temp file(s) in %s", len(swept), self.root)

        if create:
            self.git.init()
            for reserved in RESERVED_DIRS:
                (self.root / reserved).mkdir(exist_ok=True)
            self.engine_dir.mkdir(exist_ok=True)
        elif not self.git.initialized:
            raise VaultNotFoundError(
                f"{self.root} is not a git-backed vault. Fix: open it with create=True."
            )

        recoveries = self.git.recover_stale_locks()
        for recovery in recoveries:
            if not recovery.removed:
                logger.warning(
                    "git lock %s in %s is only %.1fs old — left in place (may be a live "
                    "external git process)",
                    recovery.path,
                    self.root,
                    recovery.age_seconds,
                )

        if create:
            self._ensure_gitignore()
            self._ensure_manifest(purpose)

        self._refresh_sync()
        self._load_manifest()
        self._opened = True

        if create and self.git.head() is None:
            paths = self.git.dirty_paths()
            if paths:
                self.git.commit_paths(
                    paths,
                    build_commit_message(
                        attribution,
                        f"initialize vault {self.name}",
                        operation="init",
                    ),
                    attribution,
                )
        return self.info()

    def _ensure_gitignore(self) -> None:
        path = self.root / ".gitignore"
        if not path.exists():
            atomic_write_text(path, GITIGNORE_BLOCK)
            return
        current = path.read_text(encoding="utf-8")
        if ".palaia/" not in current:
            atomic_write_text(path, current.rstrip("\n") + "\n\n" + GITIGNORE_BLOCK)

    def _ensure_manifest(self, purpose: str | None) -> None:
        path = self.root / MANIFEST_PATH
        if path.exists():
            return
        manifest = {
            "title": "Vault",
            "permalink": "meta/vault",
            "type": "meta",
            "vault_format": VAULT_FORMAT_VERSION,
            "name": self.name,
            "purpose": purpose or f"palaia vault '{self.name}'.",
        }
        body = (
            f"{purpose or f'palaia vault {self.name}.'}\n\n"
            "This file is the vault manifest (format spec §1.2). `name` and "
            "`purpose` are what clients see when they connect.\n"
        )
        atomic_write_text(path, fm.render(manifest, body))

    def _load_manifest(self) -> None:
        path = self.root / MANIFEST_PATH
        if not path.exists():
            self._writable = True
            return
        parsed = fm.parse(path.read_text(encoding="utf-8"))
        raw_version = parsed.frontmatter.get("vault_format", VAULT_FORMAT_VERSION)
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            version = VAULT_FORMAT_VERSION
        self._format_version = version
        self._writable = version <= VAULT_FORMAT_VERSION
        purpose, _ = fm.string_value(parsed.frontmatter, "purpose")
        self._purpose = purpose
        name, _ = fm.string_value(parsed.frontmatter, "name")
        if name and self.name == "default":
            self.name = name
        if not self._writable:
            logger.warning(
                "vault %s declares vault_format %s (this engine writes %s) — read-only",
                self.root,
                version,
                VAULT_FORMAT_VERSION,
            )

    async def close(self) -> None:
        """Release in-memory state. Files and git are already durable."""
        async with self._lock:
            self._entries = {}
            self._tables = _Lookups()
            self._snapshot = _EMPTY_SNAPSHOT
            self._opened = False

    # ------------------------------------------------------------------ catalog

    async def refresh(self) -> int:
        """Rebuild the identity catalog from files; return the note count."""
        async with self._lock:
            return await asyncio.to_thread(self._refresh_sync)

    def read_note_at(self, relative: str) -> Note:
        """Blocking read of the note at an exact vault-relative path."""
        return self._read_note_sync(relative)

    def _refresh_sync(self) -> int:
        entries: dict[str, CatalogEntry] = {}
        tables = _Lookups()
        for path in self._iter_note_paths():
            entry = self._read_entry(path)
            if entry is not None:
                entries[entry.path] = entry
                tables.add(entry)
        self._entries = entries
        self._tables = tables
        self._publish_catalog()
        return len(entries)

    def _iter_note_paths(self) -> list[Path]:
        found: list[Path] = []
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:  # pragma: no cover - vanished under us
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name in IGNORED_DIRS:
                        continue
                    stack.append(entry)
                    continue
                if entry.name.endswith(TEMP_SUFFIX) or not entry.name.endswith(NOTE_SUFFIX):
                    continue
                found.append(entry)
        return sorted(found)

    def _read_entry(self, path: Path) -> CatalogEntry | None:
        try:
            data = path.read_bytes()
            stat = path.stat()
        except OSError:  # pragma: no cover - vanished under us
            return None
        text = data.decode("utf-8", errors="replace")
        parsed = fm.parse(text)
        relative = self._relative(path)
        title, _ = fm.string_value(parsed.frontmatter, "title")
        permalink, _ = fm.string_value(parsed.frontmatter, "permalink")
        return CatalogEntry(
            path=relative,
            permalink=permalink or None,
            title=title or _stem(relative),
            aliases=tuple(fm.string_list(parsed.frontmatter.get("aliases"))),
            checksum=sha256_bytes(data),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    @property
    def catalog(self) -> Mapping[str, CatalogEntry]:
        """Read-only view of the identity catalog, keyed by vault-relative path.

        An immutable snapshot: safe to iterate from any thread while writes
        land, and never changed afterwards — read the property again for the
        current state.
        """
        return self._snapshot.entries

    def _publish_catalog(self) -> None:
        """Replace the readers' snapshot with the writer's current state.

        Every lock-holding operation ends with this. Inside
        :meth:`catalog_batch` the publish waits for the block's end, so a loop
        of updates copies the catalog once rather than once per entry.
        """
        if self._deferring_publish:
            return
        self._snapshot = _CatalogSnapshot(
            MappingProxyType(dict(self._entries)), self._tables.copy()
        )

    @contextmanager
    def catalog_batch(self) -> Iterator[None]:
        """Publish one snapshot for many catalog updates.

        For the lock holder only: the engine's own operations run inside one,
        and :class:`~palaia_hub.vault.watcher.VaultWatcher` wraps each batch of
        external changes it applies under :attr:`lock`. Readers keep the
        previous snapshot until the block ends — also when it ends with an
        exception, so what they see afterwards is exactly what the writer's
        copy holds.
        """
        if self._deferring_publish:
            yield
            return
        self._deferring_publish = True
        try:
            yield
        finally:
            self._deferring_publish = False
            self._publish_catalog()

    def _catalog_put(self, entry: CatalogEntry) -> None:
        previous = self._entries.get(entry.path)
        self._entries[entry.path] = entry
        if previous is not None:
            self._tables.remove(previous)
        self._tables.add(entry)

    def _catalog_drop(self, path: str) -> CatalogEntry | None:
        entry = self._entries.pop(path, None)
        if entry is not None:
            self._tables.remove(entry)
        return entry

    # --------------------------------------------------------------- resolution

    def normalize_path(self, raw: str) -> str:
        """Normalize a caller-supplied path to a vault-relative note path."""
        candidate = raw.strip()
        if candidate.startswith(MEMORY_SCHEME):
            candidate = candidate[len(MEMORY_SCHEME) :]
        candidate = candidate.replace("\\", "/").lstrip("/")
        if not candidate:
            raise InvalidPathError(
                "empty path. Fix: pass a vault-relative path like 'projects/api.md'."
            )
        parts: list[str] = []
        for part in candidate.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                raise InvalidPathError(
                    f"path {raw!r} escapes the vault root. Fix: use a path inside the vault."
                )
            parts.append(part)
        if parts and parts[0] in IGNORED_DIRS:
            raise InvalidPathError(
                f"path {raw!r} points at engine-private or VCS storage ({parts[0]}). "
                f"Fix: write vault content outside {parts[0]}."
            )
        relative = "/".join(parts)
        if not relative.endswith(NOTE_SUFFIX):
            relative += NOTE_SUFFIX
        return relative

    def resolve(self, reference: str) -> CatalogEntry:
        """Resolve a reference to a note (format spec §3.2 resolution order).

        Order: exact permalink → alias → exact title (case-insensitive) →
        unique path suffix. Ambiguity raises with the candidates listed —
        never a silent pick.
        """
        candidate = reference.strip()
        if candidate.startswith(MEMORY_SCHEME):
            candidate = candidate[len(MEMORY_SCHEME) :]
        candidate = candidate.lstrip("/")
        if not candidate:
            raise NoteNotFoundError("empty reference. Fix: pass a permalink, title or path.")

        entry = self._resolve_candidate(candidate)
        if entry is not None:
            return entry
        # `memory://<vault>/<permalink>` — strip a leading vault-name segment.
        prefix = f"{self.name}/"
        if candidate.startswith(prefix):
            entry = self._resolve_candidate(candidate[len(prefix) :])
            if entry is not None:
                return entry
        raise NoteNotFoundError(
            f"no note in vault {self.name!r} matches {reference!r}. "
            f"Fix: check the permalink, title or path (resolution order: permalink, "
            f"alias, title, path suffix)."
        )

    def _resolve_candidate(self, candidate: str) -> CatalogEntry | None:
        # One snapshot for the whole lookup: tables and entries agree with
        # each other even while a write is publishing a newer state.
        snapshot = self._snapshot
        tables = snapshot.lookups
        path = tables.by_permalink.get(candidate)
        if path is None:
            path = tables.by_alias.get(candidate.lower())
        if path is None:
            titles = tables.by_title.get(candidate.lower())
            if titles:
                if len(titles) > 1:
                    raise AmbiguousReferenceError(
                        f"title {candidate!r} matches {len(titles)} notes "
                        f"({', '.join(sorted(titles))}). Fix: reference the permalink instead."
                    )
                path = titles[0]
        if path is None:
            path = self._resolve_by_path(candidate, snapshot.entries)
        if path is None:
            return None
        return snapshot.entries.get(path)

    @staticmethod
    def _resolve_by_path(candidate: str, catalog: Mapping[str, CatalogEntry]) -> str | None:
        normalized = candidate if candidate.endswith(NOTE_SUFFIX) else candidate + NOTE_SUFFIX
        normalized = normalized.lstrip("/")
        if normalized in catalog:
            return normalized
        matches = [
            path for path in catalog if path == normalized or path.endswith("/" + normalized)
        ]
        if len(matches) > 1:
            raise AmbiguousReferenceError(
                f"path suffix {candidate!r} matches {len(matches)} notes "
                f"({', '.join(sorted(matches))}). Fix: use the full path or the permalink."
            )
        return matches[0] if matches else None

    # -------------------------------------------------------------------- reads

    async def read_note(self, reference: str) -> Note:
        """Read a note by permalink, alias, title or path."""
        self._require_open()
        entry = self.resolve(reference)
        return await asyncio.to_thread(self._read_note_sync, entry.path)

    def _read_note_sync(self, relative: str) -> Note:
        path = self.root / relative
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise NoteNotFoundError(
                f"note {relative!r} vanished from {self.root}. Fix: run the doctor "
                f"(engine.verify()) to reconcile the catalog with the files."
            ) from exc
        return self._note_from_bytes(relative, data)

    def _note_from_bytes(self, relative: str, data: bytes) -> Note:
        text = data.decode("utf-8", errors="replace")
        parsed = fm.parse(text)
        title, _ = fm.string_value(parsed.frontmatter, "title")
        permalink, _ = fm.string_value(parsed.frontmatter, "permalink")
        return Note(
            path=relative,
            permalink=permalink or None,
            title=title or _stem(relative),
            frontmatter=dict(parsed.frontmatter),
            body=parsed.body,
            text=text,
            checksum=sha256_bytes(data),
            aliases=tuple(fm.string_list(parsed.frontmatter.get("aliases"))),
            malformed_frontmatter=parsed.malformed,
        )

    async def list_dir(self, relative: str = ".") -> list[DirEntry]:
        """List directories, notes and attachments directly under ``relative``."""
        self._require_open()
        return await asyncio.to_thread(self._list_dir_sync, relative)

    def _list_dir_sync(self, relative: str) -> list[DirEntry]:
        base = self.root if relative in (".", "", "/") else self.root / relative.strip("/")
        if not base.exists() or not base.is_dir():
            raise NoteNotFoundError(
                f"directory {relative!r} does not exist in vault {self.name!r}. "
                f"Fix: check the path, or create a note in it (parents are created)."
            )
        catalog = self._snapshot.entries
        entries: list[DirEntry] = []
        for child in sorted(base.iterdir()):
            if child.name in IGNORED_DIRS or child.name.endswith(TEMP_SUFFIX):
                continue
            rel = self._relative(child)
            if child.is_dir():
                entries.append(DirEntry(path=rel, kind="dir"))
            elif child.name.endswith(NOTE_SUFFIX):
                catalog_entry = catalog.get(rel)
                entries.append(
                    DirEntry(
                        path=rel,
                        kind="note",
                        permalink=catalog_entry.permalink if catalog_entry else None,
                        title=catalog_entry.title if catalog_entry else _stem(rel),
                        size=child.stat().st_size,
                    )
                )
            else:
                entries.append(DirEntry(path=rel, kind="file", size=child.stat().st_size))
        return entries

    async def history(self, reference: str, *, limit: int = 50) -> list[CommitInfo]:
        """Return the git history of one note, following moves."""
        self._require_open()
        entry = self.resolve(reference)
        return await asyncio.to_thread(lambda: self.git.log(entry.path, limit=limit))

    # ------------------------------------------------------------------- writes

    async def write_note(
        self,
        path: str,
        *,
        body: str = "",
        title: str | None = None,
        frontmatter: Mapping[str, Any] | None = None,
        permalink: str | None = None,
        attribution: Attribution = ENGINE,
        summary: str | None = None,
        expected_checksum: str | None = None,
        must_create: bool = False,
    ) -> WriteResult:
        """Create or replace a note at ``path`` and commit it.

        Returns only after the file is on disk (fsync'd) and committed.

        Args:
            path: vault-relative path; ``.md`` is appended if missing.
            body: the note body (Markdown, unparsed by this SPEC).
            title: frontmatter title; defaults to the existing one or the
                filename stem. Volatile titles are rejected (§4.1).
            frontmatter: extra frontmatter keys to set; a ``None`` value
                deletes the key. Unknown keys are preserved verbatim.
            permalink: force a permalink (must be canonical and free);
                by default an existing one is kept, otherwise one is minted.
            expected_checksum: optimistic concurrency — the write is refused
                with :class:`ChecksumConflictError` if the file's current
                checksum differs.
            must_create: refuse if the note already exists.
        """
        self._require_writable()
        return await self._locked(
            lambda: self._write_note_sync(
                path,
                body=body,
                title=title,
                extra=frontmatter,
                permalink=permalink,
                attribution=attribution,
                summary=summary,
                expected_checksum=expected_checksum,
                must_create=must_create,
                merge=False,
                operation="write",
            )
        )

    async def edit_note(
        self,
        reference: str,
        *,
        body: str | None = None,
        frontmatter: Mapping[str, Any] | None = None,
        title: str | None = None,
        expected_checksum: str,
        attribution: Attribution = ENGINE,
        summary: str | None = None,
    ) -> WriteResult:
        """Edit an existing note, preserving what the caller did not touch.

        ``expected_checksum`` is required: an edit is a read-modify-write, and
        a stale checksum means someone else wrote the note in between — that
        must fail loudly (:class:`ChecksumConflictError`), not overwrite.
        """
        self._require_writable()
        entry = self.resolve(reference)
        return await self._locked(
            lambda: self._write_note_sync(
                entry.path,
                body=body,
                title=title,
                extra=frontmatter,
                permalink=None,
                attribution=attribution,
                summary=summary,
                expected_checksum=expected_checksum,
                must_create=False,
                merge=True,
                operation="edit",
            )
        )

    def _write_note_sync(
        self,
        path: str,
        *,
        body: str | None,
        title: str | None,
        extra: Mapping[str, Any] | None,
        permalink: str | None,
        attribution: Attribution,
        summary: str | None,
        expected_checksum: str | None,
        must_create: bool,
        merge: bool,
        operation: Operation,
    ) -> tuple[WriteResult, list[ChangeEvent]]:
        relative = self.normalize_path(path)
        target = self.root / relative
        exists = target.exists()
        existing: Note | None = self._read_note_sync(relative) if exists else None

        if existing is not None:
            self._refuse_malformed(existing)
        if must_create and exists:
            raise NoteExistsError(
                f"note {relative!r} already exists in vault {self.name!r}. "
                f"Fix: call edit_note(), or write without must_create=True to replace it."
            )
        if expected_checksum is not None:
            if existing is None:
                raise NoteNotFoundError(
                    f"note {relative!r} does not exist, so it cannot be edited. "
                    f"Fix: use write_note() to create it."
                )
            if existing.checksum != expected_checksum:
                raise ChecksumConflictError(
                    f"note {relative!r} changed since you read it "
                    f"(expected {expected_checksum[:12]}…, on disk {existing.checksum[:12]}…). "
                    f"Fix: re-read the note, re-apply your change, and write again."
                )

        merged: dict[str, Any] = dict(existing.frontmatter) if (existing and merge) else {}
        if existing and not merge:
            # A replace keeps the identity keys the engine owns; everything
            # else is the caller's to restate.
            for key in ("permalink", "created", "aliases"):
                if key in existing.frontmatter:
                    merged[key] = existing.frontmatter[key]
        for key, value in (extra or {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value

        resolved_title = (
            title
            or (fm.string_value(merged, "title")[0] if "title" in merged else None)
            or (existing.title if existing else _stem(relative))
        )
        self._reject_volatile("title", resolved_title)

        resolved_permalink = self._resolve_write_permalink(
            relative=relative,
            requested=permalink,
            merged=merged,
            title=resolved_title,
        )

        now = fm.utc_now_iso()
        merged["title"] = resolved_title
        merged["permalink"] = resolved_permalink
        merged.setdefault("type", "note")
        merged.setdefault("created", now)
        origin = attribution.frontmatter_origin()
        if origin:
            merged["origin"] = origin

        # `modified` is stamped only if something else actually changed —
        # otherwise a re-write of identical content would produce a commit
        # whose only diff is a timestamp, and `modified` would stop meaning
        # "when this note last changed". A caller that sets `modified`
        # explicitly keeps control of it.
        caller_set_modified = "modified" in (extra or {})
        if not caller_set_modified:
            merged["modified"] = (
                existing.frontmatter.get("modified", now) if existing is not None else now
            )

        resolved_body = body if body is not None else (existing.body if existing else "")
        text = fm.render(merged, resolved_body)
        if existing is not None and text == existing.text:
            # Nothing changed: no write, no empty commit — unless this very
            # content is still waiting for its commit (issue #333): then the
            # retry is what commits it.
            commit = self._recover_uncommitted(only=relative)
            return (
                WriteResult(note=existing, commit=commit, created=False, operation=operation),
                [],
            )
        if existing is not None and not caller_set_modified:
            merged["modified"] = now
            text = fm.render(merged, resolved_body)

        self._sweep_external_edits()
        data = atomic_write_text(target, text)
        note = self._note_from_bytes(relative, data)
        self._catalog_put(
            CatalogEntry(
                path=relative,
                permalink=note.permalink,
                title=note.title,
                aliases=note.aliases,
                checksum=note.checksum,
                size=len(data),
                mtime_ns=target.stat().st_mtime_ns,
            )
        )
        event: ChangeEvent = (
            NoteCreated(
                vault=self.name,
                path=relative,
                permalink=note.permalink,
                checksum=note.checksum,
            )
            if not exists
            else NoteModified(
                vault=self.name,
                path=relative,
                permalink=note.permalink,
                checksum=note.checksum,
                previous_checksum=existing.checksum if existing else None,
            )
        )
        commit = self._commit_changes(
            [relative],
            build_commit_message(
                attribution,
                summary or f"{'write' if not exists else 'edit'} {resolved_permalink}",
                operation=operation,
                permalinks=[resolved_permalink],
            ),
            attribution,
            events=[event],
        )
        return (
            WriteResult(note=note, commit=commit, created=not exists, operation=operation),
            [event],
        )

    def _refuse_malformed(self, note: Note) -> None:
        """Never rebuild frontmatter from an empty parse (issue #335).

        A fence that is present but unparseable parses to ``{}``; rendering
        that back would replace the user's YAML block — custom keys, a
        half-typed edit — with the engine's identity keys alone.
        """
        if not note.malformed_frontmatter:
            return
        raise MalformedFrontmatterError(
            f"note {note.path!r} in vault {self.name!r} has frontmatter that does not "
            f"parse as YAML, so the engine refuses to rewrite it (it would lose the "
            f"original block). Fix: repair the frontmatter between the '---' fences in "
            f"that file with your editor, then retry."
        )

    def _commit_changes(
        self,
        paths: Sequence[str],
        message: str,
        attribution: Attribution,
        *,
        events: Sequence[ChangeEvent],
    ) -> str | None:
        """Commit ``paths``; on failure remember them and raise (issue #333).

        The files are already on disk and in the catalog when this runs. A
        commit that fails (an ``index.lock`` held by another git process is
        the usual reason) must not turn into a silent divergence: the paths
        are queued with their message and attribution, and the next
        successful engine operation — or a retry of the same write — commits
        them first. The change events travel on the exception so
        :meth:`_locked` can still publish them: the index reflects disk.
        """
        try:
            return self.git.commit_paths(paths, message, attribution)
        except GitError as exc:
            for path in paths:
                self._uncommitted[path] = (message, attribution)
            raise UncommittedWriteError(
                f"{exc}. The change is on disk and will be committed by the next "
                f"successful write to this vault. Fix: release the git lock (close the "
                f"other git process or remove a stale .git/index.lock) and retry.",
                events=events,
            ) from exc

    def _recover_uncommitted(self, *, only: str | None = None) -> str | None:
        """Commit writes whose commit failed earlier; return the last sha.

        With ``only``, just that path (a retry of the same write); otherwise
        everything queued, grouped by the original message so history reads
        as if the commits had succeeded the first time.
        """
        if not self._uncommitted:
            return None
        if only is not None:
            pending = {only: self._uncommitted[only]} if only in self._uncommitted else {}
        else:
            pending = dict(self._uncommitted)
        groups: dict[tuple[str, Attribution], list[str]] = {}
        for path, key in pending.items():
            groups.setdefault(key, []).append(path)
        commit: str | None = None
        for (message, attribution), paths in groups.items():
            commit = self.git.commit_paths(paths, message, attribution)
            for path in paths:
                self._uncommitted.pop(path, None)
            logger.info("committed %d earlier write(s) whose commit had failed", len(paths))
        return commit

    def _resolve_write_permalink(
        self,
        *,
        relative: str,
        requested: str | None,
        merged: Mapping[str, Any],
        title: str,
    ) -> str:
        tables = self._tables
        current = self._entries.get(relative)
        own = {current.permalink} if current and current.permalink else set()

        if requested is not None:
            if not pl.is_canonical(requested):
                raise VaultError(
                    f"permalink {requested!r} is not canonical (allowed: lowercase "
                    f"[a-z0-9-] segments joined by '/'). Fix: pass a canonical "
                    f"permalink or omit it and let the engine mint one."
                )
            self._reject_volatile("permalink", requested)
            if requested in tables.permalinks and requested not in own:
                raise PermalinkConflictError(
                    f"permalink {requested!r} is already used by "
                    f"{tables.by_permalink[requested]!r}. Fix: choose another permalink."
                )
            return requested

        existing_permalink, _ = fm.string_value(merged, "permalink")
        if existing_permalink:
            # Identity never changes on write or move (§3.1) — keep it verbatim,
            # even when non-canonical (the doctor offers canonicalization).
            return existing_permalink

        minted = pl.mint(relative, title)
        self._reject_volatile("permalink", minted)
        return pl.make_unique(minted, tables.permalinks)

    def _reject_volatile(self, kind: str, value: str) -> None:
        violations = pl.volatility_violations(value)
        if violations:
            raise VolatileNameError(pl.describe_violations(kind, value, violations))

    async def move_note(
        self,
        reference: str,
        new_path: str,
        *,
        attribution: Attribution = ENGINE,
        summary: str | None = None,
    ) -> WriteResult:
        """Move/rename a note's *file*. The permalink does not change (§3.1)."""
        self._require_writable()
        entry = self.resolve(reference)
        return await self._locked(
            lambda: self._move_note_sync(entry.path, new_path, attribution, summary)
        )

    def _move_note_sync(
        self,
        relative: str,
        new_path: str,
        attribution: Attribution,
        summary: str | None,
    ) -> tuple[WriteResult, list[ChangeEvent]]:
        destination = self.normalize_path(new_path)
        if destination == relative:
            note = self._read_note_sync(relative)
            return WriteResult(note=note, commit=None, operation="move"), []
        target = self.root / destination
        if target.exists():
            raise NoteExistsError(
                f"cannot move {relative!r} to {destination!r}: a note already exists there. "
                f"Fix: choose another path or delete the existing note first."
            )
        self._sweep_external_edits()
        atomic_move(self.root / relative, target)
        previous = self._catalog_drop(relative)
        note = self._read_note_sync(destination)
        self._catalog_put(
            CatalogEntry(
                path=destination,
                permalink=note.permalink or (previous.permalink if previous else None),
                title=note.title,
                aliases=note.aliases,
                checksum=note.checksum,
                size=target.stat().st_size,
                mtime_ns=target.stat().st_mtime_ns,
            )
        )
        event = NoteMoved(
            vault=self.name,
            path=destination,
            previous_path=relative,
            permalink=note.permalink,
            checksum=note.checksum,
        )
        commit = self._commit_changes(
            [relative, destination],
            build_commit_message(
                attribution,
                summary or f"move {relative} -> {destination}",
                operation="move",
                permalinks=[note.permalink] if note.permalink else [],
            ),
            attribution,
            events=[event],
        )
        return WriteResult(note=note, commit=commit, operation="move"), [event]

    async def delete_note(
        self,
        reference: str,
        *,
        attribution: Attribution = ENGINE,
        summary: str | None = None,
    ) -> WriteResult:
        """Delete a note and commit the removal."""
        self._require_writable()
        entry = self.resolve(reference)
        return await self._locked(lambda: self._delete_note_sync(entry.path, attribution, summary))

    def _delete_note_sync(
        self, relative: str, attribution: Attribution, summary: str | None
    ) -> tuple[WriteResult, list[ChangeEvent]]:
        target = self.root / relative
        if not target.exists():
            raise NoteNotFoundError(
                f"note {relative!r} does not exist in vault {self.name!r}. "
                f"Fix: nothing to delete — refresh the catalog with engine.refresh()."
            )
        entry = self._entries.get(relative)
        self._sweep_external_edits()
        durable_unlink(target)
        self._catalog_drop(relative)
        event = NoteDeleted(
            vault=self.name,
            path=relative,
            permalink=entry.permalink if entry else None,
        )
        commit = self._commit_changes(
            [relative],
            build_commit_message(
                attribution,
                summary or f"delete {entry.permalink if entry and entry.permalink else relative}",
                operation="delete",
                permalinks=[entry.permalink] if entry and entry.permalink else [],
            ),
            attribution,
            events=[event],
        )
        return WriteResult(note=None, commit=commit, operation="delete"), [event]

    # ---------------------------------------------------------- identity rename

    async def rename_entity(
        self,
        reference: str,
        new_title: str,
        *,
        new_permalink: str | None = None,
        rename_file: bool = False,
        attribution: Attribution = ENGINE,
        summary: str | None = None,
    ) -> RenameResult:
        """Rename a note's identity: new title/permalink, aliases, backlinks.

        Total and atomic per format spec §4.2: the new permalink is minted,
        the old title and permalink are appended to ``aliases`` (so existing
        ``memory://`` references keep resolving), **every** inbound wikilink
        in the vault is rewritten, and the whole operation is one commit.
        """
        self._require_writable()
        entry = self.resolve(reference)
        return await self._locked(
            lambda: self._rename_entity_sync(
                entry.path, new_title, new_permalink, rename_file, attribution, summary
            )
        )

    def _rename_entity_sync(
        self,
        relative: str,
        new_title: str,
        new_permalink: str | None,
        rename_file: bool,
        attribution: Attribution,
        summary: str | None,
    ) -> tuple[RenameResult, list[ChangeEvent]]:
        note = self._read_note_sync(relative)
        self._refuse_malformed(note)
        old_title = note.title
        old_permalink = note.permalink
        self._reject_volatile("title", new_title)

        tables = self._tables
        if new_permalink is not None:
            if not pl.is_canonical(new_permalink):
                raise VaultError(
                    f"permalink {new_permalink!r} is not canonical. Fix: use lowercase "
                    f"[a-z0-9-] segments joined by '/'."
                )
            self._reject_volatile("permalink", new_permalink)
            if new_permalink in tables.permalinks and new_permalink != old_permalink:
                raise PermalinkConflictError(
                    f"permalink {new_permalink!r} is already used by "
                    f"{tables.by_permalink[new_permalink]!r}. Fix: choose another permalink."
                )
            minted = new_permalink
        else:
            candidate = pl.mint(relative, new_title)
            self._reject_volatile("permalink", candidate)
            taken = set(tables.permalinks) - ({old_permalink} if old_permalink else set())
            minted = pl.make_unique(candidate, taken)

        self._sweep_external_edits()

        aliases = list(note.aliases)
        for value in (old_title, old_permalink):
            if value and value != new_title and value != minted and value not in aliases:
                aliases.append(value)

        renamed_frontmatter = dict(note.frontmatter)
        renamed_frontmatter["title"] = new_title
        renamed_frontmatter["permalink"] = minted
        renamed_frontmatter["aliases"] = aliases
        renamed_frontmatter["modified"] = fm.utc_now_iso()
        origin = attribution.frontmatter_origin()
        if origin:
            renamed_frontmatter["origin"] = origin

        target_relative = relative
        changed: list[str] = []
        if rename_file:
            folder = relative.rsplit("/", 1)[0] if "/" in relative else ""
            stem = pl.slugify(new_title) or _stem(relative)
            candidate_path = f"{folder}/{stem}{NOTE_SUFFIX}" if folder else f"{stem}{NOTE_SUFFIX}"
            if candidate_path != relative and not (self.root / candidate_path).exists():
                atomic_move(self.root / relative, self.root / candidate_path)
                self._catalog_drop(relative)
                changed.append(relative)
                target_relative = candidate_path

        data = atomic_write_text(
            self.root / target_relative, fm.render(renamed_frontmatter, note.body)
        )
        changed.append(target_relative)
        renamed = self._note_from_bytes(target_relative, data)
        self._catalog_put(_entry_from_note(renamed, self.root / target_relative))

        rewritten = self._rewrite_backlinks(
            skip=target_relative,
            old_title=old_title,
            old_permalink=old_permalink,
            old_paths=(relative, target_relative),
            new_title=new_title,
            new_permalink=minted,
        )
        changed.extend(rewritten)

        result = RenameResult(
            note=renamed,
            commit=None,
            old_title=old_title,
            old_permalink=old_permalink,
            rewritten=rewritten,
        )
        events: list[ChangeEvent] = [
            EntityRenamed(
                vault=self.name,
                path=target_relative,
                permalink=minted,
                previous_permalink=old_permalink,
                title=new_title,
                previous_title=old_title,
                rewritten_links=result.rewritten_links,
            )
        ]
        commit = self._commit_changes(
            changed,
            build_commit_message(
                attribution,
                summary or f"rename {old_permalink or old_title} -> {minted}",
                operation="rename",
                permalinks=[minted],
            ),
            attribution,
            events=events,
        )
        return replace(result, commit=commit), events

    def _rewrite_backlinks(
        self,
        *,
        skip: str,
        old_title: str,
        old_permalink: str | None,
        old_paths: tuple[str, ...],
        new_title: str,
        new_permalink: str,
    ) -> dict[str, int]:
        """Rewrite every inbound wikilink; return ``{path: rewritten_count}``."""
        title_forms = {old_title.lower()}
        permalink_forms = {value.lower() for value in (old_permalink,) if value}
        for old_path in old_paths:
            if old_path.endswith(NOTE_SUFFIX):
                permalink_forms.add(old_path[: -len(NOTE_SUFFIX)].lower())
            permalink_forms.add(old_path.lower())
        # A path-shaped form must not shadow another note's permalink: if some
        # other entity owns that exact permalink, links using it mean *that*
        # note, not this one.
        claims = self._tables.by_permalink
        permalink_forms = {
            form for form in permalink_forms if claims.get(form) in (None, *old_paths)
        }

        def resolve(target: str) -> str | None:
            probe = target.strip()
            if probe.startswith(MEMORY_SCHEME):
                probe = probe[len(MEMORY_SCHEME) :]
            lowered = probe.lower()
            if lowered in title_forms:
                return new_title
            if lowered in permalink_forms:
                return new_permalink
            return None

        rewritten: dict[str, int] = {}
        for path in list(self._entries):
            if path == skip:
                continue
            file_path = self.root / path
            try:
                text = file_path.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover - vanished under us
                continue
            new_text, count = rewrite_targets(text, resolve)
            if count == 0:
                continue
            atomic_write_text(file_path, new_text)
            note = self._note_from_bytes(path, new_text.encode("utf-8"))
            self._catalog_put(_entry_from_note(note, file_path))
            rewritten[path] = count
        return rewritten

    # -------------------------------------------------------- external activity

    def _sweep_external_edits(self) -> str | None:
        """Commit changes made outside the engine as their own human commit.

        Format spec §10: external edits become their own attributed commit on
        the next engine activity, so an engine commit never silently contains
        someone else's work. ``git status`` was measured cheap even at 10k
        notes (~20 ms, SPEC-003 Q3), which is what makes this affordable on
        the write path.
        """
        if not self.commit_external_edits or not self.git.initialized:
            return None
        # Engine writes whose commit failed earlier are committed first, with
        # their own message and attribution — they are not external edits.
        self._recover_uncommitted()
        dirty = self.git.dirty_paths()
        if not dirty:
            return None
        for path in dirty:
            if not path.endswith(NOTE_SUFFIX):
                continue
            candidate = self.root / path
            if candidate.exists():
                entry = self._read_entry(candidate)
                if entry is not None:
                    self._catalog_put(entry)
            else:
                self._catalog_drop(path)
        commit = self.git.commit_paths(
            dirty,
            build_commit_message(
                HUMAN,
                f"external edits ({len(dirty)} path{'s' if len(dirty) != 1 else ''})",
                operation="external",
            ),
            HUMAN,
        )
        if commit:
            logger.info("committed %d external change(s) in %s", len(dirty), self.root)
        return commit

    async def commit_external_changes(self) -> str | None:
        """Commit any external edits now, without writing anything else."""
        self._require_writable()
        async with self._lock:
            return await asyncio.to_thread(self._sweep_and_publish)

    def _sweep_and_publish(self) -> str | None:
        with self.catalog_batch():
            return self._sweep_external_edits()

    @property
    def lock(self) -> asyncio.Lock:
        """The engine's write lock, for the one other component that mutates
        the catalog: :class:`~palaia_hub.vault.watcher.VaultWatcher` holds it
        while it applies a batch of external changes (in a worker thread,
        inside :meth:`catalog_batch`), so a batch never interleaves with an
        engine write and readers see it land as one snapshot (issue #331)."""
        return self._lock

    def known_entry(self, relative: str) -> CatalogEntry | None:
        """The writer's current record of ``relative`` — for the lock holder.

        Inside a :meth:`catalog_batch` this already reflects the batch's own
        earlier updates, which :attr:`catalog` (the readers' snapshot) does
        not show until the batch ends. The watcher needs exactly that view to
        tell a repeat report of a file it just catalogued from a real change.
        """
        return self._entries.get(relative)

    def observe_external_change(
        self, relative: str, *, deleted: bool = False, permalink: str | None = None
    ) -> CatalogEntry | None:
        """Update the catalog after an out-of-engine change (watcher callback).

        The caller holds :attr:`lock`. Outside a :meth:`catalog_batch` each
        call publishes on its own.
        """
        if deleted:
            dropped = self._catalog_drop(relative)
            self._publish_catalog()
            return dropped
        entry = self._read_entry(self.root / relative)
        if entry is None:
            return None
        if entry.permalink is None and permalink is not None:
            entry = CatalogEntry(
                path=entry.path,
                permalink=permalink,
                title=entry.title,
                aliases=entry.aliases,
                checksum=entry.checksum,
                size=entry.size,
                mtime_ns=entry.mtime_ns,
            )
        self._catalog_put(entry)
        self._publish_catalog()
        return entry

    # ------------------------------------------------------------ housekeeping

    async def gc(self, *, aggressive: bool = False) -> None:
        """Run git housekeeping now (the scheduled part of the gc policy)."""
        async with self._lock:
            await asyncio.to_thread(lambda: self.git.gc(aggressive=aggressive))

    async def recover_locks(self, *, stale_after: float | None = None) -> list[LockRecovery]:
        """Detect and clear stale git locks (crash recovery)."""
        return await asyncio.to_thread(
            lambda: self.git.recover_stale_locks(stale_after=stale_after)
        )

    # ------------------------------------------------------------ doctor hooks

    async def verify(self, index: IndexView | None = None) -> list[Finding]:
        """Run the doctor's consistency checks (see :class:`~.doctor.VaultDoctor`).

        Pass the SPEC-104 index to include file↔index drift checks.
        """
        from .doctor import VaultDoctor

        return await VaultDoctor(self).verify(index)

    async def repair(self) -> list[Finding]:
        """Perform the doctor's safe repairs (stale locks, orphaned temp files)."""
        from .doctor import VaultDoctor

        return await VaultDoctor(self).repair()

    async def reindex(self, sink: ReindexSink) -> int:
        """Feed every note to ``sink`` — the rebuild-from-files hook point."""
        from .doctor import VaultDoctor

        return await VaultDoctor(self).reindex(sink)

    async def assign_missing_permalinks(self, *, attribution: Attribution = ENGINE) -> list[str]:
        """Assign permalinks to notes that lack one, in one attributed commit.

        Format spec §3.1: files arriving without a permalink (imports,
        hand-created notes) get one at first index via a write-back commit.
        """
        self._require_writable()
        return await self._locked(lambda: self._assign_missing_permalinks_sync(attribution))

    def _assign_missing_permalinks_sync(
        self, attribution: Attribution
    ) -> tuple[list[str], list[ChangeEvent]]:
        missing = [entry for entry in self._entries.values() if not entry.permalink]
        if not missing:
            return [], []
        self._sweep_external_edits()
        taken = set(self._tables.permalinks)
        assigned: list[str] = []
        changed: list[str] = []
        events: list[ChangeEvent] = []
        for entry in missing:
            note = self._read_note_sync(entry.path)
            if note.malformed_frontmatter:
                # Its permalink is "missing" only because the block did not
                # parse; rewriting it would destroy the block (issue #335).
                logger.warning(
                    "not assigning a permalink to %s: its frontmatter does not parse",
                    entry.path,
                )
                continue
            minted = pl.make_unique(pl.mint(entry.path, note.title), taken)
            taken.add(minted)
            updated = dict(note.frontmatter)
            updated["title"] = note.title
            updated["permalink"] = minted
            updated.setdefault("type", "note")
            updated.setdefault("created", fm.utc_now_iso())
            updated["modified"] = fm.utc_now_iso()
            data = atomic_write_text(self.root / entry.path, fm.render(updated, note.body))
            rewritten = self._note_from_bytes(entry.path, data)
            self._catalog_put(_entry_from_note(rewritten, self.root / entry.path))
            assigned.append(minted)
            changed.append(entry.path)
            events.append(
                NoteModified(
                    vault=self.name,
                    path=entry.path,
                    permalink=minted,
                    checksum=rewritten.checksum,
                    previous_checksum=note.checksum,
                )
            )
        if not changed:
            return [], []
        self._commit_changes(
            changed,
            build_commit_message(
                attribution,
                f"assign permalinks to {len(assigned)} note(s)",
                operation="index",
                permalinks=assigned,
            ),
            attribution,
            events=events,
        )
        return assigned, events

    # ------------------------------------------------------------------ helpers

    def _require_open(self) -> None:
        if not self._opened:
            raise VaultError(f"vault {self.name!r} is not open. Fix: await engine.open() first.")

    def _require_writable(self) -> None:
        self._require_open()
        if not self._writable:
            raise VaultFormatVersionError(
                f"vault {self.root} declares vault_format {self._format_version}, but this "
                f"engine writes version {VAULT_FORMAT_VERSION}. Reads stay best-effort; "
                f"writes are refused. Fix: upgrade palaia, or migrate the vault."
            )

    async def _locked(self, operation: Callable[[], tuple[T, list[ChangeEvent]]]) -> T:
        def run() -> tuple[T, list[ChangeEvent]]:
            # One published snapshot per operation, whatever it touched.
            with self.catalog_batch():
                return operation()

        try:
            async with self._lock:
                result, events = await asyncio.to_thread(run)
        except UncommittedWriteError as exc:
            # The files changed even though the commit did not (issue #333):
            # subscribers — the index above all — must learn about it.
            if self.bus is not None and exc.events:
                await self.bus.publish_all(cast("list[ChangeEvent]", list(exc.events)))
            raise
        if self.bus is not None and events:
            await self.bus.publish_all(events)
        return result


def _entry_from_note(note: Note, path: Path) -> CatalogEntry:
    stat = path.stat()
    return CatalogEntry(
        path=note.path,
        permalink=note.permalink,
        title=note.title,
        aliases=note.aliases,
        checksum=note.checksum,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )


def _stem(relative: str) -> str:
    name = relative.rsplit("/", 1)[-1]
    return name[: -len(NOTE_SUFFIX)] if name.endswith(NOTE_SUFFIX) else name
