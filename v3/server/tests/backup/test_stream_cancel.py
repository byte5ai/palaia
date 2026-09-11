"""Issue #368: a download that stops being read does not leak its builder.

The archive is built on a worker thread that hands chunks to a bounded
queue. When the client disconnected, the consuming generator was closed but
the builder stayed blocked in ``put()`` for the life of the process — one
thread, its buffered chunks, tar state and an open file handle per aborted
download. The builder now watches a cancellation flag and unwinds.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from palaia_hub.backup import iter_archive_bytes

THREAD_NAME = "palaia-backup-build"


def _builders() -> set[int | None]:
    return {t.ident for t in threading.enumerate() if t.name == THREAD_NAME}


def test_closing_the_download_stops_the_builder_thread(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "vaults").mkdir(parents=True)
    # Incompressible and far bigger than the queue can hold, so the builder
    # is blocked on a full queue when the consumer walks away.
    (home / "vaults" / "blob.bin").write_bytes(os.urandom(6 * 1024 * 1024))
    before = _builders()

    stream = iter_archive_bytes(home)
    assert next(stream), "the first chunk arrives"
    time.sleep(0.3)
    assert _builders() - before, "the builder is alive and blocked behind the full queue"

    stream.close()

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _builders() - before:
        time.sleep(0.05)
    assert not (_builders() - before), "the builder thread ended once the consumer left"


def test_a_completed_download_leaves_no_builder_behind(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "vaults").mkdir(parents=True)
    (home / "vaults" / "note.md").write_text("hello\n", encoding="utf-8")
    before = _builders()

    data = b"".join(iter_archive_bytes(home))

    assert data.startswith(b"\x1f\x8b"), "gzip magic"
    assert not (_builders() - before)
