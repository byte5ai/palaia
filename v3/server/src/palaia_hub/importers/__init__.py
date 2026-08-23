"""Importers: palaia v2 stores and basic-memory vaults (SPEC-111).

Nobody starts from zero: :mod:`.v2_source` reads a palaia v2 ``.palaia/``
store and :mod:`.basic_memory_source` reads a basic-memory vault; both map
their entries into format-spec-valid v3 notes with preserved metadata (see
``docs/import-mappings.md``). :mod:`.runner` drives either source through a
:class:`palaia_hub.vault.engine.VaultEngine`, in dry-run or apply mode.

Reading a user's own files has no license implications (ADR-002) — but no
code from either source project is imported or copied; both readers are
clean-room re-implementations of the on-disk formats, referencing only this
repository's v2 tree (as an on-disk format reference, never as a dependency)
and the public concept dossier in ``v3/research/basic-memory.md``.
"""

from __future__ import annotations

from .embed_queue import EmbedQueueStatus, enqueue_for_embedding, queue_status
from .models import ImportOutcome, ImportReport, MappedNote, SkippedItem
from .runner import ImportRunner

__all__ = [
    "EmbedQueueStatus",
    "ImportOutcome",
    "ImportReport",
    "ImportRunner",
    "MappedNote",
    "SkippedItem",
    "enqueue_for_embedding",
    "queue_status",
]
