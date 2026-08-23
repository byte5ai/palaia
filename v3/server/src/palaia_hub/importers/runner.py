"""Drive a mapped source through the vault engine — dry-run or apply.

Both sources (:mod:`.v2_source`, :mod:`.basic_memory_source`) reduce to the
same shape: an iterable of :class:`~.models.MappedNote` /
:class:`~.models.SkippedItem`. :class:`ImportRunner` is the one place that
actually talks to :class:`~palaia_hub.vault.engine.VaultEngine`, so
idempotence, dry-run, and the cold-embed queue seam are implemented once.
"""

from __future__ import annotations

from collections.abc import Iterable

from palaia_hub.vault.engine import VaultEngine
from palaia_hub.vault.errors import NoteExistsError, VaultError, VolatileNameError
from palaia_hub.vault.frontmatter import utc_now_iso
from palaia_hub.vault.models import Attribution

from .embed_queue import enqueue_for_embedding
from .models import ImportedItem, ImportReport, MappedNote, SkippedItem

#: The attribution every import commit carries (vault-format.md §2.1 origin).
IMPORT_ATTRIBUTION = Attribution(client="palaia-hub-import")


class ImportRunner:
    """Runs a mapped-item iterable against one open :class:`VaultEngine`.

    Idempotence: a :class:`MappedNote`'s permalink is deterministic from its
    source identity (never from title/content — see each source module), so
    re-running an import that produced no new source items writes nothing:
    every permalink already resolves and is reported ``already-imported``.
    """

    def __init__(self, engine: VaultEngine) -> None:
        self.engine = engine

    async def run(
        self,
        source_name: str,
        source_path: str,
        mapped: Iterable[MappedNote | SkippedItem],
        *,
        dry_run: bool,
    ) -> ImportReport:
        report = ImportReport(source=source_name, source_path=source_path, dry_run=dry_run)
        for item in mapped:
            if isinstance(item, SkippedItem):
                report.skipped.append(item)
                continue
            report.items.append(await self._apply_one(item, dry_run=dry_run))
        return report

    async def _apply_one(self, note: MappedNote, *, dry_run: bool) -> ImportedItem:
        existing = self._already_imported(note.permalink)
        if existing:
            return ImportedItem(
                source_path=note.source_path,
                permalink=note.permalink,
                outcome="already-imported",
                detail="permalink already exists in the vault (idempotent skip)",
            )
        if dry_run:
            return ImportedItem(
                source_path=note.source_path,
                permalink=note.permalink,
                outcome="created",
                detail=f"would create: {note.describe}",
            )
        try:
            result = await self.engine.write_note(
                note.permalink,
                body=note.body,
                title=note.title,
                frontmatter=note.frontmatter,
                permalink=note.permalink,
                attribution=IMPORT_ATTRIBUTION,
                summary=f"import: {note.describe}",
                must_create=True,
            )
        except (NoteExistsError, VolatileNameError) as exc:
            # A concurrent import, or a permalink that collides with a
            # volatile-name-rejected mint from an *unrelated* write between
            # our idempotence check and this call — surface it as skipped
            # rather than failing the whole run.
            return ImportedItem(
                source_path=note.source_path,
                permalink=note.permalink,
                outcome="skipped",
                detail=str(exc),
            )
        enqueue_for_embedding(
            self.engine.engine_dir, permalink=note.permalink, enqueued_at=utc_now_iso()
        )
        return ImportedItem(
            source_path=note.source_path,
            permalink=note.permalink,
            outcome="created",
            detail=note.describe,
            commit=result.commit,
        )

    def _already_imported(self, permalink: str) -> bool:
        try:
            self.engine.resolve(permalink)
        except VaultError:
            return False
        return True


__all__ = ["IMPORT_ATTRIBUTION", "ImportRunner"]
