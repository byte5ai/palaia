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
  old content or the complete new content, never a torn mix. A vault's own
  ``.git`` history is git's content-addressed object store, immutable once
  written; only refs move, and a ref update is itself a single ``rename``.

So every *individual* file in the archive is internally consistent. What is
**not** claimed: that the archive is one atomic snapshot *across* stores —
two different stores written to in the same second could land a heartbeat
apart in the archive. For a personal single-hub deployment with no
distributed transaction spanning multiple stores, that gap is not a real
risk; it is written down here, not glossed over, exactly as the SPEC asks.

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

import logging
import os
import queue
import sqlite3
import tarfile
import threading
import time
from collections.abc import Iterator
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


def _sorted_walk(home: Path) -> Iterator[Path]:
    """Every directory and file under ``home``, deterministically ordered.

    ``followlinks=False``: a hub home never legitimately contains a symlink
    to outside itself, and following one could walk arbitrarily far off the
    home this archive is supposed to be scoped to.
    """
    for dirpath, dirnames, filenames in os.walk(home, followlinks=False):
        dirnames.sort()
        current = Path(dirpath)
        if current != home:
            yield current
        for name in sorted(filenames):
            yield current / name


def _add_tree(tar: tarfile.TarFile, home: Path) -> None:
    sqlite_bases: set[Path] = set()
    for path in _sorted_walk(home):
        rel = path.relative_to(home)
        rel_posix = rel.as_posix()
        if _is_excluded_index_path(rel_posix):
            continue
        if path.is_dir():
            info = tar.gettarinfo(str(path), arcname=rel_posix)
            tar.addfile(info)
            continue
        if path.is_symlink():
            # No legitimate use in a hub home; never followed, never stored.
            continue
        if _looks_like_sqlite(path):
            data = _snapshot_sqlite(path)
            info = tarfile.TarInfo(rel_posix)
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            info.mode = 0o600
            tar.addfile(info, _BytesReader(data))
            sqlite_bases.add(path)
            continue
        base_name = _strip_sqlite_sibling_suffix(path.name)
        if base_name != path.name and (path.parent / base_name) in sqlite_bases:
            # Represented by the snapshot above — its pages are exactly
            # what this write-ahead/journal file holds.
            continue
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


class _QueueWriter:
    """A write-only file object that hands ``tarfile``'s output to a queue
    in fixed-size chunks, so :func:`iter_archive_bytes` can stream them out
    without the whole archive ever existing as one in-memory object."""

    def __init__(self, sink: queue.Queue[bytes | BaseException | None]) -> None:
        self._sink = sink
        self._buffer = bytearray()

    def write(self, data: bytes) -> int:
        self._buffer.extend(data)
        while len(self._buffer) >= _CHUNK_SIZE:
            self._sink.put(bytes(self._buffer[:_CHUNK_SIZE]))
            del self._buffer[:_CHUNK_SIZE]
        return len(data)

    def flush(self) -> None:  # pragma: no cover - gzip calls this; no-op
        pass

    def close_out(self) -> None:
        if self._buffer:
            self._sink.put(bytes(self._buffer))
            self._buffer.clear()


def _build_in_thread(home: Path, sink: queue.Queue[bytes | BaseException | None]) -> None:
    writer = _QueueWriter(sink)
    try:
        with tarfile.open(fileobj=writer, mode="w|gz") as tar:  # type: ignore[call-overload]
            _add_tree(tar, home)
        writer.close_out()
    except BaseException as exc:  # noqa: BLE001 - handed to the consumer, not swallowed
        logger.exception("backup archive build failed")
        sink.put(exc)
        return
    sink.put(None)


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
    builder = threading.Thread(
        target=_build_in_thread, args=(home, sink), daemon=True, name="palaia-backup-build"
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
        builder.join(timeout=5.0)


__all__ = [
    "ARCHIVE_MEDIA_TYPE",
    "BackupError",
    "archive_filename",
    "iter_archive_bytes",
]
