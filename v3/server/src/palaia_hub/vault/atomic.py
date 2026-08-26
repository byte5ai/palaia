"""Atomic, durable file primitives.

The write protocol is the one MASTERPLAN §5.1 promises and the SPEC-003
kill-test validated (0 corrupt files in 25 SIGKILL trials): write into a
temporary file **in the target directory**, ``flush``, ``fsync``, then
``os.replace`` (atomic on POSIX) — and additionally ``fsync`` the directory
so the rename itself is durable, not just the bytes.

Temp files are named ``.<final-name>.<random>.palaia-tmp``: hidden, ignored
by the vault's ``.gitignore``, ignored by the watcher, and recognizable by
:func:`sweep_temp_files` so a crash mid-write leaves no permanent litter
(the spike saw one orphaned temp file in 7 of 25 kill trials).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path

TEMP_SUFFIX = ".palaia-tmp"

# Read/hash files in chunks so a large attachment never has to fit in memory.
_CHUNK = 1 << 16


def sha256_bytes(data: bytes) -> str:
    """Return the hex sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of the file at ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_dir(path: Path) -> None:
    """``fsync`` a directory so entry creations/renames inside it are durable.

    Best effort: platforms that cannot open a directory for reading (Windows)
    raise, and there is nothing useful to do about it — the rename is still
    atomic there, only its durability across a power loss is weaker.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform dependent
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - platform dependent
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically and durably.

    The call returns only once the bytes and the directory entry are on
    stable storage — there is no accepted-but-unwritten state.
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=TEMP_SUFFIX, dir=parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    fsync_dir(parent)


def atomic_write_text(path: Path, text: str) -> bytes:
    """Write ``text`` as UTF-8 (LF endings) atomically; return the bytes written."""
    data = text.encode("utf-8")
    atomic_write_bytes(path, data)
    return data


def atomic_move(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst`` atomically, creating ``dst``'s parent if needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    fsync_dir(dst.parent)
    if dst.parent != src.parent:
        fsync_dir(src.parent)


def durable_unlink(path: Path) -> None:
    """Delete ``path`` and ``fsync`` its directory so the removal is durable."""
    path.unlink(missing_ok=True)
    fsync_dir(path.parent)


def sweep_temp_files(root: Path, *, min_age_seconds: float = 0.0) -> list[Path]:
    """Delete leftover engine temp files under ``root``; return what was removed.

    A temp file older than ``min_age_seconds`` cannot belong to an in-flight
    write of this process (writes are serialized per vault), so it is crash
    residue. Called on vault open and by the doctor.
    """
    removed: list[Path] = []
    now = time.time()
    for candidate in root.rglob(f"*{TEMP_SUFFIX}"):
        if not candidate.is_file():
            continue
        try:
            if now - candidate.stat().st_mtime < min_age_seconds:
                continue
            candidate.unlink()
        except OSError:  # pragma: no cover - raced with another sweeper
            continue
        removed.append(candidate)
    return removed
