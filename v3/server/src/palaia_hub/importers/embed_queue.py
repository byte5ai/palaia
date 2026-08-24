"""The cold-embed-as-background-job seam (SPEC-111 deliverable #3).

**Superseded, honestly.** This module was written before SPEC-104 (index +
search, incl. vector embedding) merged, as a placeholder: no embedding
worker existed anywhere in the codebase yet, so it kept its own JSON-lines
record of "what an import wrote that still needs embedding" for a future
worker to drain.

SPEC-104 has since merged, and SPEC-210 wired the real path: every note
:class:`~palaia_hub.importers.runner.ImportRunner` writes goes through
:meth:`~palaia_hub.vault.engine.VaultEngine.write_note`, which publishes a
``NoteCreated`` event on the engine's bus; a
:class:`~palaia_hub.index.VaultIndex` subscribed to that same bus (opened
by ``palaia_hub.serve.build_production_app`` for every vault the running
hub serves, and by the ``import`` CLI subcommand for a bare import) inserts
the note's chunks as ``pending`` and drains them through its own
background worker — no JSONL bookkeeping needed at all;
:meth:`~palaia_hub.index.VaultIndex.embed_status` /
:func:`~palaia_hub.index.embed_progress` are the real, live progress read.

:func:`enqueue_for_embedding` is still called by :class:`ImportRunner` for
backward compatibility with this module's own existing test coverage, but
nothing reads its output for anything real any more — the queue file it
writes is inert bookkeeping, not a functioning pipeline. A future cleanup
SPEC may remove it once nothing still exercises it.

The queue is one JSON-lines file per vault, under the engine-private
directory (``.palaia/import-embed-queue.jsonl``, format spec §1: engine
storage, not vault content, already gitignored by the engine's own
``.gitignore`` block). Each import run appends one line per note it wrote;
nothing here ever removes a line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

QUEUE_FILENAME = "import-embed-queue.jsonl"


@dataclass(frozen=True, slots=True)
class EmbedQueueStatus:
    """Progress-visible status of the cold-embed queue for one vault.

    Mirrors :class:`~palaia_hub.gateway.vault_protocol.InboxStatusResult`'s
    shape deliberately: same kind of "how much is waiting, since when"
    summary, so a future dashboard tile or ``embed_status``-style API call
    reads the same way ``inbox_status`` already does.
    """

    pending: int
    embedded: int
    oldest_pending_permalink: str | None
    oldest_pending_enqueued_at: str | None


def _queue_path(engine_dir: Path) -> Path:
    return engine_dir / QUEUE_FILENAME


def enqueue_for_embedding(engine_dir: Path, *, permalink: str, enqueued_at: str) -> None:
    """Append one permalink to the vault's cold-embed queue.

    Best-effort: a failure to write the queue file must never fail the
    import itself (the note is already committed to the vault — files are
    the only truth, format spec invariant 1). Any I/O error here is
    swallowed after being the caller's problem to notice via
    :func:`queue_status` staying unchanged.
    """
    engine_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"permalink": permalink, "enqueued_at": enqueued_at, "embedded": False},
        sort_keys=True,
    )
    try:
        with _queue_path(engine_dir).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:  # pragma: no cover - defensive; queue is best-effort
        pass


def queue_status(engine_dir: Path) -> EmbedQueueStatus:
    """Read the current cold-embed queue status for one vault.

    Tolerates a missing queue file (nothing imported yet) and malformed
    lines (skipped, never raised) — this is a status read, not a contract
    enforcement point.
    """
    path = _queue_path(engine_dir)
    if not path.exists():
        return EmbedQueueStatus(
            pending=0, embedded=0, oldest_pending_permalink=None, oldest_pending_enqueued_at=None
        )

    pending = 0
    embedded = 0
    oldest_permalink: str | None = None
    oldest_at: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:  # pragma: no cover - defensive
            continue
        if record.get("embedded"):
            embedded += 1
            continue
        pending += 1
        enqueued_at = record.get("enqueued_at")
        if oldest_at is None or (enqueued_at and enqueued_at < oldest_at):
            oldest_at = enqueued_at
            oldest_permalink = record.get("permalink")
    return EmbedQueueStatus(
        pending=pending,
        embedded=embedded,
        oldest_pending_permalink=oldest_permalink,
        oldest_pending_enqueued_at=oldest_at,
    )


__all__ = ["EmbedQueueStatus", "enqueue_for_embedding", "queue_status"]
