"""The cold-embed-as-background-job seam (SPEC-111 deliverable #3).

**Honest scope note:** SPEC-104 (index + search, incl. vector embedding) is
being built in parallel on its own branch and is not merged. This module
does *not* compute any embeddings — there is no embedding model wired into
this codebase yet. What it does is the part SPEC-111 owns regardless of
that: make sure an import never blocks on embedding work, and leave a
durable, inspectable queue that a future embedding worker (SPEC-104, or a
later wiring SPEC) can drain, plus a progress-visible status read in the
same shape as SPEC-107's ``inbox_status`` so the dashboard/API story is
already consistent.

The queue is one JSON-lines file per vault, under the engine-private
directory (``.palaia/import-embed-queue.jsonl``, format spec §1: engine
storage, not vault content, already gitignored by the engine's own
``.gitignore`` block). Each import run appends one line per note it wrote;
nothing here ever removes a line — that is the future worker's job, via
:func:`mark_embedded`, once it exists. Until then the queue simply grows,
which is the correct visible symptom of "no embedding worker has run yet".
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
