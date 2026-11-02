"""The backup archive: everything a restore needs, streamed as one ``tar.gz``
(SPEC-604 deliverable #1).

**What is in the archive.** The whole hub home, byte for byte: ``config.yaml``,
``vaults.yaml``, every vault (notes, git history, manifest), the OAuth store
and its signing key, the upstream secret store *and* its encryption key
(``upstream/secrets.py`` — a backup that cannot restore secrets is not a
backup), tokens, hooks, automations, notifications, the marketplace caches,
the funnel stats, the mode-change audit log. The one thing left out on
purpose:

**What is excluded, and why that is safe.** Each vault's search index
(``<vault>/.palaia/index.sqlite3`` — see :data:`palaia_hub.index.db.
INDEX_RELATIVE_PATH`) is rebuildable state, not a system of record — the
notes on disk are. It is excluded to keep the archive small. This is safe
*because* :meth:`palaia_hub.index.service.VaultIndex.open` already rebuilds
it from the vault's notes on every hub start (``build=True`` by default,
called from ``serve.py`` and ``cli.py`` for every vault) — restoring an
archive with no index file is exactly the state a hub is in the first time
it ever opens a vault, and that path is exercised on every boot already, not
invented for this feature. ``server/tests/backup/test_archive.py`` and the
SPEC-604 e2e round trip both prove the rebuild happens.

**The consistency claim, stated honestly.** There is no cross-store quiesce
lock in this hub — building one would be new machinery invented for this
feature alone, which the SPEC explicitly asks not to do ("use what each
store already supports, don't invent"). What each store already supports:

* Every SQLite database (found by content — the on-disk magic header, not by
  filename convention, since stores use both ``.sqlite3`` and ``.db``) is
  captured through SQLite's own online backup API
  (:meth:`sqlite3.Connection.backup`) into an in-memory database, then
  serialized with :meth:`sqlite3.Connection.serialize`. That is a
  transactionally consistent snapshot as of one moment, taken *through* the
  database engine rather than by copying bytes off disk — it is correct even
  while another connection holds the file open in WAL mode with committed
  pages still sitting in ``-wal``, unlike a raw file copy. Those ``-wal``/
  ``-shm``/``-journal`` siblings are therefore never added to the archive
  themselves; the snapshot already contains everything they hold.
* Everything else this hub persists (``config.yaml``, ``vaults.yaml``, vault
  notes, the YAML stores) is written via
  :func:`palaia_hub.vault.atomic.atomic_write_bytes` — a temp file plus
  ``os.replace`` — so a plain read mid-write can only ever see the complete
  old content or the complete new content, never a torn mix.
* A vault's ``.git`` is one repository whose files must agree with each
  other: every commit a ref names has to be in the archived object store
  (issue #605 — a commit landing between "objects archived" and "refs
  archived" used to restore as ``invalid sha1 pointer``). Two things git
  itself guarantees make that hold here. Objects are written before the
  ref that names them moves, and are never changed afterwards; so the
  repository's refs, ``HEAD`` and the rest of its metadata are archived
  *first* and its ``objects/`` *last* (:func:`_git_dir_walk`) — every
  object an archived ref can reach already existed when the ref was read.
  Objects only ever disappear through git's maintenance (``gc``: repack,
  prune), and git serializes that through its own ``gc.pid`` lock; the
  backup holds that lock for the time it reads one repository
  (:func:`_git_maintenance_paused`), so a ``git gc`` started meanwhile —
  the vault's automatic one or the doctor's — skips instead of deleting
  objects out from under the archive. A commit made during the backup is
  simply not in it, or its objects are present without a ref naming them,
  which git treats as harmless.

So every *individual* file and every vault repository in the archive is
internally consistent. What is **not** claimed: that the archive is one
atomic snapshot *across* stores — two different stores written to in the
same second could land a heartbeat apart in the archive, and a vault's notes
can be a write ahead of or behind its history (the next write commits the
difference). For a personal single-hub deployment with no distributed
transaction spanning multiple stores, that gap is not a real risk; it is
written down here, not glossed over, exactly as the SPEC asks.

**Where it never touches disk.** The archive is built entirely in memory and
on the wire: SQLite snapshots live in a Python ``bytes`` object just long
enough to become one tar member, and the tar/gzip stream itself is written
straight to the queue :func:`iter_archive_bytes` drains — this module never
creates a temp file, so there is no window where a full copy of the hub's
secrets sits in a world-readable temp directory. See
:mod:`palaia_hub.backup_api` for the ``GET /api/backup`` route this backs,
which is reachable only behind the admin session gate
(:mod:`palaia_hub.admin_session`) — see that module's docstring for why
every ``/api/*`` route is gated by construction.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import socket
import sqlite3
import tarfile
import threading
import time
from collections.abc import Generator, Iterator
from pathlib import Path

from .index.db import INDEX_RELATIVE_PATH

logger = logging.getLogger("palaia_hub.backup")

#: The filename the download offers, timestamped so successive backups from
#: the same hub never collide in a browser's downloads folder.
ARCHIVE_MEDIA_TYPE = "application/gzip"

#: SQLite's own on-disk magic header (see the file format doc, §1.3) — used
#: to find databases *by content*, since this repository's stores use both
#: ``.sqlite3`` and ``.db`` for the same thing (``upstream/secrets.py`` vs.
#: ``curator/wiring.py``'s ``STASH_FILENAME``) and a name-based rule would
#: silently miss one the day a new store picks yet another convention.
_SQLITE_MAGIC = b"SQLite format 3\x00"

#: The write-ahead/rollback siblings SQLite creates next to a database
#: (:data:`palaia_hub.security.files.SQLITE_SIBLING_SUFFIXES` minus the
#: empty string — that one *is* the database). Never added to the archive
#: on their own: the online-backup snapshot of the base file already
#: contains every page they hold.
_SQLITE_SIBLING_SUFFIXES = ("-wal", "-shm", "-journal")

#: How large a chunk :func:`iter_archive_bytes` yields at a time. Large
#: enough that gzip's own framing overhead is negligible, small enough that
#: the archive streams rather than buffering minutes of output before the
#: first byte reaches the client.
_CHUNK_SIZE = 256 * 1024

#: Backpressure: the builder thread blocks once this many chunks are queued
#: and not yet sent, so a slow client cannot make this module buffer an
#: unbounded amount of a hub's data in memory.
_QUEUE_DEPTH = 4

#: How long a backup waits for a ``git gc`` already running in a vault before
#: it gives up with a message (issue #605). A vault's gc takes seconds; this
#: only bounds a pathological one.
_GIT_GC_WAIT_SECONDS = 120.0
_GIT_GC_POLL_SECONDS = 0.5

#: git's own staleness rule for ``gc.pid`` (``builtin/gc.c``): a lock file
#: older than this is ignored by every ``git gc``, so it is ignored here too.
_GIT_GC_PID_STALE_SECONDS = 12 * 3600

#: ``gc.pid.lock`` exists only for the instant git takes or hands over the gc
#: lock. One this old is crash residue — and while it exists no ``git gc`` can
#: start at all (git dies on it), so the backup needs no lock of its own.
_GIT_GC_LOCKFILE_STALE_SECONDS = 10.0


class BackupError(RuntimeError):
    """Building the archive failed. The message names the offending path,
    never file contents."""


def archive_filename(*, now: float | None = None) -> str:
    """The download's suggested filename, timestamped to the second (UTC)."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    return f"palaia-backup-{stamp}.tar.gz"


def _strip_sqlite_sibling_suffix(name: str) -> str:
    for suffix in _SQLITE_SIBLING_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_excluded_index_path(rel_posix: str) -> bool:
    """Is ``rel_posix`` a vault's search index, or one of its siblings?

    Matches at any depth, because a vault's path under the hub home is
    whatever the operator (or the wizard) chose — only the *tail* is fixed
    by the index's own layout.
    """
    return _strip_sqlite_sibling_suffix(rel_posix).endswith(INDEX_RELATIVE_PATH)


def _looks_like_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            header = handle.read(len(_SQLITE_MAGIC))
    except OSError:
        return False
    return header == _SQLITE_MAGIC


def _snapshot_sqlite(path: Path) -> bytes:
    """A consistent point-in-time copy of the SQLite database at ``path``.

    Goes through SQLite's own online-backup API rather than reading the
    file's bytes directly — see this module's docstring for why that
    matters with a WAL-mode writer possibly still attached. The destination
    is an in-memory database, serialized to ``bytes``
    (:meth:`sqlite3.Connection.serialize`, Python 3.11+): nothing here ever
    touches disk.
    """
    try:
        # Not opened with ``mode=ro`` URI: that would need the path
        # percent-encoded (hub homes can contain spaces), and ``.backup()``
        # never issues a write against the source regardless of how it was
        # opened.
        source = sqlite3.connect(str(path))
    except sqlite3.Error as exc:
        raise BackupError(f"could not open {path.name} for backup: {exc}") from exc
    try:
        destination = sqlite3.connect(":memory:")
        try:
            source.backup(destination)
            return destination.serialize()
        finally:
            destination.close()
    except sqlite3.Error as exc:
        raise BackupError(f"could not snapshot {path.name}: {exc}") from exc
    finally:
        source.close()


def _sorted_walk(home: Path) -> Generator[Path, None, None]:
    """Every directory and file under ``home``, deterministically ordered.

    ``followlinks=False``: a hub home never legitimately contains a symlink
    to outside itself, and following one could walk arbitrarily far off the
    home this archive is supposed to be scoped to.

    A git repository (a vault's ``.git``) is not walked in plain order but by
    :func:`_git_dir_walk` — metadata first, objects last, under git's gc
    lock — see this module's docstring for why (issue #605).
    """
    for dirpath, dirnames, filenames in os.walk(home, followlinks=False):
        dirnames.sort()
        current = Path(dirpath)
        if current != home:
            yield current
        for name in sorted(filenames):
            yield current / name
        for name in [d for d in dirnames if _is_git_dir(current / d)]:
            dirnames.remove(name)
            yield from _git_dir_walk(current / name)


def _plain_walk(top: Path, *, skip: Path | None = None) -> Iterator[Path]:
    """Directories and files under ``top`` (not ``top`` itself), sorted, never
    following a symlink and never entering ``skip``."""
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        current = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if current / d != skip)
        if current != top:
            yield current
        for name in sorted(filenames):
            yield current / name


def _is_git_dir(path: Path) -> bool:
    """A real (not symlinked) git directory: ``.git`` with an object store."""
    return (
        path.name == ".git"
        and not path.is_symlink()
        and (path / "objects").is_dir()
        and (path / "HEAD").is_file()
    )


def _git_dir_walk(git_dir: Path) -> Generator[Path, None, None]:
    """One repository's paths in the order that keeps it restorable.

    Everything but ``objects/`` first — refs, ``HEAD``, ``packed-refs``,
    config, logs — then ``objects/``, with git's maintenance held off for the
    whole repository (:func:`_git_maintenance_paused`). Lock files (git's
    in-flight ``*.lock``, the backup's own ``gc.pid``) and git's temporary
    object files (``tmp_*``) are left out: they are not repository content,
    and restoring one would only get in git's way.
    """
    objects = git_dir / "objects"
    with _git_maintenance_paused(git_dir):
        yield git_dir
        for path in _plain_walk(git_dir, skip=objects):
            if path.name.endswith(".lock") or path == git_dir / "gc.pid":
                continue
            yield path
        yield objects
        for path in _plain_walk(objects):
            if path.name.startswith("tmp_"):
                continue
            yield path


def _gc_holder(pidfile: Path, host: str) -> str | None:
    """Who holds git's gc lock (``gc.pid``) right now, or ``None``.

    Mirrors ``lock_repo_for_gc`` in git's ``builtin/gc.c``: a ``gc.pid``
    counts while it is younger than 12 hours, names a process, and that
    process is alive on this host — or the host is another machine, which
    git gives the benefit of the doubt.
    """
    try:
        age = time.time() - pidfile.stat().st_mtime
        raw = pidfile.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return None
    if age > _GIT_GC_PID_STALE_SECONDS:
        return None
    pid_text, _, locking_host = raw.partition(" ")
    if not pid_text.isdigit() or not locking_host:
        return None
    if locking_host != host:
        return raw
    try:
        os.kill(int(pid_text), 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return raw
    return raw


def _take_gc_lock(git_dir: Path, mine: str, host: str) -> bool | None:
    """Try once to take git's gc lock the way ``git gc`` does.

    Returns ``True`` when the backup now holds ``gc.pid``, ``None`` when no
    lock is needed because a stale ``gc.pid.lock`` already stops every
    ``git gc`` from starting, and ``False`` when a gc is running or taking
    the lock right now.
    """
    pidfile = git_dir / "gc.pid"
    lockfile = git_dir / "gc.pid.lock"
    try:
        fd = os.open(lockfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        try:
            age = time.time() - lockfile.stat().st_mtime
        except FileNotFoundError:
            return False
        if age >= _GIT_GC_LOCKFILE_STALE_SECONDS and _gc_holder(pidfile, host) is None:
            return None
        return False
    committed = False
    try:
        if _gc_holder(pidfile, host) is not None:
            return False
        os.write(fd, mine.encode("utf-8"))
        os.close(fd)
        fd = -1
        os.replace(lockfile, pidfile)
        committed = True
        return True
    finally:
        if fd >= 0:
            os.close(fd)
        if not committed:
            with contextlib.suppress(FileNotFoundError):
                lockfile.unlink()


@contextlib.contextmanager
def _git_maintenance_paused(git_dir: Path) -> Iterator[None]:
    """Hold git's own gc lock for the time the backup reads ``git_dir``.

    Every ``git gc`` — the vault's automatic ``gc --auto`` and the doctor's
    scheduled one — checks ``gc.pid`` first and skips (``--auto``) or refuses
    while it names a live process. That is the only path by which objects
    leave a vault's store, so holding it keeps every object the archived
    refs reach on disk until the archive has read it (issue #605). A gc that
    is already running is waited for, up to :data:`_GIT_GC_WAIT_SECONDS`.
    """
    host = socket.gethostname()
    mine = f"{os.getpid()} {host}"
    deadline = time.monotonic() + _GIT_GC_WAIT_SECONDS
    while (held := _take_gc_lock(git_dir, mine, host)) is False:
        if time.monotonic() >= deadline:
            raise BackupError(
                f"git maintenance is still running in {git_dir.parent.name}; "
                "try the backup again in a few minutes"
            )
        time.sleep(_GIT_GC_POLL_SECONDS)
    try:
        yield
    finally:
        if held:
            pidfile = git_dir / "gc.pid"
            with contextlib.suppress(OSError):
                if pidfile.read_text(encoding="utf-8") == mine:
                    pidfile.unlink()


def _add_tree(tar: tarfile.TarFile, home: Path) -> None:
    sqlite_bases: set[Path] = set()
    with contextlib.closing(_sorted_walk(home)) as walk:
        for path in walk:
            _add_member(tar, home, path, sqlite_bases)


def _add_member(tar: tarfile.TarFile, home: Path, path: Path, sqlite_bases: set[Path]) -> None:
    rel_posix = path.relative_to(home).as_posix()
    if _is_excluded_index_path(rel_posix):
        return
    if path.is_dir():
        info = tar.gettarinfo(str(path), arcname=rel_posix)
        tar.addfile(info)
        return
    if path.is_symlink():
        # No legitimate use in a hub home; never followed, never stored.
        return
    if _looks_like_sqlite(path):
        data = _snapshot_sqlite(path)
        # The live file's owner, like every other member: a restore that
        # keeps ownership (tar run as root, the documented way) must hand
        # the database back to the user palaia runs as, not to root.
        info = tar.gettarinfo(str(path), arcname=rel_posix)
        info.size = len(data)
        info.mode = 0o600
        tar.addfile(info, _BytesReader(data))
        sqlite_bases.add(path)
        return
    base_name = _strip_sqlite_sibling_suffix(path.name)
    if base_name != path.name and (path.parent / base_name) in sqlite_bases:
        # Represented by the snapshot above — its pages are exactly what
        # this write-ahead/journal file holds.
        return
    info = tar.gettarinfo(str(path), arcname=rel_posix)
    with path.open("rb") as handle:
        tar.addfile(info, handle)


class _BytesReader:
    """The minimal read-only file object :meth:`tarfile.TarFile.addfile`
    needs, over an in-memory snapshot. Avoids pulling in ``io.BytesIO`` just
    to note that this class exists solely to hand ``bytes`` through the same
    ``addfile(info, fileobj)`` path every other tar member uses."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos : self._pos + size]
            self._pos += len(chunk)
        return chunk


#: How long a blocked ``put`` waits before re-checking whether the consumer
#: has gone away (issue #368) — the ceiling on how long an abandoned build
#: keeps its thread after the client disconnected.
_CANCEL_POLL_SECONDS = 0.25


class _BuildCancelled(Exception):
    """The consumer stopped reading; the builder unwinds quietly."""


class _QueueWriter:
    """A write-only file object that hands ``tarfile``'s output to a queue
    in fixed-size chunks, so :func:`iter_archive_bytes` can stream them out
    without the whole archive ever existing as one in-memory object.

    Every ``put`` watches ``cancelled`` (issue #368): a client that
    disconnects mid-download closes the consuming generator, and the builder
    — blocked on a full queue nobody drains any more — used to live on for
    the whole process lifetime with its buffered chunks, tar state and an
    open file handle. Now it notices within :data:`_CANCEL_POLL_SECONDS`
    and stops.
    """

    def __init__(
        self, sink: queue.Queue[bytes | BaseException | None], cancelled: threading.Event
    ) -> None:
        self._sink = sink
        self._cancelled = cancelled
        self._buffer = bytearray()

    def put(self, item: bytes | BaseException | None) -> None:
        while True:
            if self._cancelled.is_set():
                raise _BuildCancelled
            try:
                self._sink.put(item, timeout=_CANCEL_POLL_SECONDS)
                return
            except queue.Full:
                continue

    def write(self, data: bytes) -> int:
        self._buffer.extend(data)
        while len(self._buffer) >= _CHUNK_SIZE:
            self.put(bytes(self._buffer[:_CHUNK_SIZE]))
            del self._buffer[:_CHUNK_SIZE]
        return len(data)

    def flush(self) -> None:  # pragma: no cover - gzip calls this; no-op
        pass

    def close_out(self) -> None:
        if self._buffer:
            self.put(bytes(self._buffer))
            self._buffer.clear()


def archive_holds(home: Path, path: Path) -> bool:
    """Whether a backup of ``home`` holds the directory at ``path``.

    The archive is ``home``'s own tree, with symlinks never followed
    (:func:`_sorted_walk`). A memory created in a folder elsewhere — the
    setup's and the dashboard's "Folder" option — is therefore not in it,
    and neither is one linked into ``home`` from outside; the dashboard's
    Backups page names those instead of promising every memory.
    """
    try:
        inside = home.expanduser().resolve()
        target = path.expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return target.is_relative_to(inside)


def _build_in_thread(
    home: Path, sink: queue.Queue[bytes | BaseException | None], cancelled: threading.Event
) -> None:
    writer = _QueueWriter(sink, cancelled)
    try:
        with tarfile.open(fileobj=writer, mode="w|gz") as tar:  # type: ignore[call-overload]
            _add_tree(tar, home)
        writer.close_out()
    except _BuildCancelled:
        logger.debug("backup archive build abandoned: the download was cancelled")
        return
    except BaseException as exc:  # noqa: BLE001 - handed to the consumer, not swallowed
        logger.exception("backup archive build failed")
        with contextlib.suppress(_BuildCancelled):
            writer.put(exc)
        return
    with contextlib.suppress(_BuildCancelled):
        writer.put(None)


def iter_archive_bytes(home: Path) -> Iterator[bytes]:
    """Yield the ``tar.gz`` of ``home`` in chunks, building it on a worker
    thread as it goes.

    A synchronous generator on purpose: FastAPI/Starlette hand a sync
    generator's ``content`` to
    :func:`starlette.concurrency.iterate_in_threadpool`, which runs each
    ``next()`` call — including this generator's blocking ``queue.get()`` —
    off the event loop. The archive is built by a second, dedicated thread
    so ``tarfile``'s own blocking writes never have to fit inside a single
    ``next()`` call either; the two threads only ever talk through the
    bounded queue, which is also what gives a slow client backpressure all
    the way back to the SQLite snapshot loop.
    """
    sink: queue.Queue[bytes | BaseException | None] = queue.Queue(maxsize=_QUEUE_DEPTH)
    cancelled = threading.Event()
    builder = threading.Thread(
        target=_build_in_thread,
        args=(home, sink, cancelled),
        daemon=True,
        name="palaia-backup-build",
    )
    builder.start()
    try:
        while True:
            item = sink.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item
    finally:
        # Whether the archive completed or the client went away (issue
        # #368): tell the builder to stop, free the slot it may be blocked
        # on, and wait for it — briefly, it polls the flag every quarter
        # second.
        cancelled.set()
        with contextlib.suppress(queue.Empty):
            sink.get_nowait()
        builder.join(timeout=5.0)


__all__ = [
    "ARCHIVE_MEDIA_TYPE",
    "BackupError",
    "archive_filename",
    "archive_holds",
    "iter_archive_bytes",
]
