"""Real wiring: a :class:`~.vault_protocol.VaultService` backed by the vault
engine (SPEC-102).

SPEC-105 deliberately deferred this adapter — its module docstring says so
verbatim (:mod:`palaia_hub.gateway.vault_protocol`): the vault engine ran on
a parallel branch and was not merged when the memory tool family was built.
This module is that adapter, now that SPEC-102 has landed. It is a thin
pass-through: field names already mirror ``vault-format.md`` on both sides
(:class:`~.vault_protocol.NoteRecord` / :class:`~palaia_hub.vault.Note`), so
no translation layer is needed beyond unpacking frontmatter and mapping
engine exceptions to :class:`~.vault_protocol.VaultServiceError`.

**Search** here is a linear substring scan over already-open notes — the
same trade-off :class:`~.fake_vault.FakeVaultService` made, now over real
files and frontmatter instead of an in-memory dict. SPEC-104 (the hybrid
index) is not in this SPEC's ``depends_on`` and is not merged yet; when it
lands, ``search`` is the one method here a future SPEC should replace with
an index-backed query, everything else already talks to the real vault.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from palaia_hub.vault import (
    AmbiguousReferenceError,
    ChecksumConflictError,
    InvalidPathError,
    Note,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    VaultEngine,
    VolatileNameError,
)
from palaia_hub.vault import permalink as pl

from .vault_protocol import NoteRecord, NoteSummary, SearchHit, VaultService, VaultServiceError

# Every caller-facing engine failure this adapter might see, translated to
# VaultServiceError (see vault_protocol.VaultService's docstring: tool
# wrappers catch that type and turn it into a tool-level error result rather
# than an uncaught exception). VaultConfigError/VaultNotFoundError/GitError/
# VaultFormatVersionError are open/registry/git-plumbing failures, not
# per-call caller mistakes, so they are intentionally left to propagate.
_ENGINE_CALLER_ERRORS: tuple[type[Exception], ...] = (
    AmbiguousReferenceError,
    ChecksumConflictError,
    InvalidPathError,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    VolatileNameError,
)


def _tag_list(value: Any) -> list[str]:
    """Normalize a frontmatter ``tags`` value (list or comma-string) to a
    lowercase list, per vault-format.md §2.1."""
    if value is None:
        return []
    if isinstance(value, str):
        return [tag.strip().lower() for tag in value.split(",") if tag.strip()]
    return [str(tag).strip().lower() for tag in value if str(tag).strip()]


def _folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _is_meta(note: Note) -> bool:
    """True for the vault manifest and any other ``type: meta`` note.

    Format spec §6: ``meta`` is "vault self-description... excluded from
    normal recall". ``search``/``list_notes``/``recent_activity`` are the
    tool family's normal-recall surface, so they filter it out; ``read`` and
    ``write``/``edit``/``move``/``delete`` do not — a caller that names
    ``meta/vault`` explicitly still gets it.
    """
    return str(note.frontmatter.get("type", "note")) == "meta"


def _note_to_record(note: Note) -> NoteRecord:
    frontmatter = note.frontmatter
    return NoteRecord(
        permalink=note.permalink or note.path,
        title=note.title,
        type=str(frontmatter.get("type", "note")),
        tags=_tag_list(frontmatter.get("tags")),
        folder=_folder_of(note.path),
        modified=str(frontmatter.get("modified") or ""),
        created=str(frontmatter.get("created") or ""),
        body=note.body,
    )


def _note_to_summary(note: Note) -> NoteSummary:
    record = _note_to_record(note)
    return NoteSummary(**record.model_dump(exclude={"body", "created"}))


class EngineVaultService:
    """:class:`VaultService` over one open :class:`~palaia_hub.vault.VaultEngine`.

    The engine must already be opened (``await engine.open(...)``) — this
    adapter does not manage the engine's lifecycle, only translates calls.
    """

    def __init__(self, engine: VaultEngine) -> None:
        self._engine = engine

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        needle = query.lower()
        hits: list[SearchHit] = []
        # Snapshot before iterating: every step below `await`s (read_note),
        # and the vault watcher can mutate the engine's catalog dict
        # concurrently between those awaits (external edits land while a
        # search is in flight) — iterating the live mapping would then
        # raise "dictionary changed size during iteration".
        for entry in list(self._engine.catalog.values()):
            note = await self._engine.read_note(entry.path)
            if _is_meta(note):
                continue
            haystack = f"{note.title}\n{note.body}".lower()
            if needle not in haystack:
                continue
            idx = haystack.find(needle)
            start = max(0, idx - 20)
            snippet = note.body[start : start + len(query) + 40].strip()
            hits.append(
                SearchHit(
                    permalink=note.permalink or note.path,
                    title=note.title,
                    snippet=snippet,
                    score=1.0 if needle in note.title.lower() else 0.5,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def read(self, permalink: str) -> NoteRecord:
        try:
            note = await self._engine.read_note(permalink)
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        return _note_to_record(note)

    async def write(
        self,
        title: str,
        body: str,
        *,
        folder: str = "",
        type: str = "note",  # noqa: A002 - matches the vault-format field name
        tags: list[str] | None = None,
    ) -> NoteRecord:
        folder = folder.strip("/")
        slug = pl.slugify(title) or "note"
        relative = f"{folder}/{slug}.md" if folder else f"{slug}.md"
        frontmatter: dict[str, Any] = {"type": type}
        if tags is not None:
            frontmatter["tags"] = list(tags)
        try:
            result = await self._engine.write_note(
                relative,
                body=body,
                title=title,
                frontmatter=frontmatter,
                must_create=True,
            )
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        assert result.note is not None  # write_note always returns a note
        return _note_to_record(result.note)

    async def edit(
        self,
        permalink: str,
        *,
        body: str | None = None,
        append: str | None = None,
        tags: list[str] | None = None,
    ) -> NoteRecord:
        try:
            current = await self._engine.read_note(permalink)
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        new_body = current.body
        if body is not None:
            new_body = body
        if append is not None:
            # `current.body` (and any caller-supplied `body`) already ends
            # in a trailing newline once written through the engine (its
            # canonical write form always does) — strip it first so append
            # does not leave a blank line between the old and new content.
            base = new_body.rstrip("\n")
            new_body = f"{base}\n{append}" if base else append
        frontmatter = {"tags": list(tags)} if tags is not None else None
        try:
            result = await self._engine.edit_note(
                permalink,
                body=new_body,
                frontmatter=frontmatter,
                expected_checksum=current.checksum,
            )
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        assert result.note is not None
        return _note_to_record(result.note)

    async def move(self, permalink: str, folder: str) -> NoteRecord:
        try:
            entry = self._engine.resolve(permalink)
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        filename = entry.path.rsplit("/", 1)[-1]
        folder = folder.strip("/")
        new_path = f"{folder}/{filename}" if folder else filename
        try:
            result = await self._engine.move_note(permalink, new_path)
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        assert result.note is not None
        return _note_to_record(result.note)

    async def delete(self, permalink: str) -> bool:
        try:
            await self._engine.delete_note(permalink)
        except NoteNotFoundError:
            return False
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        return True

    async def list_notes(self, *, folder: str = "") -> list[NoteSummary]:
        folder = folder.strip("/")
        summaries: list[NoteSummary] = []
        for entry in list(self._engine.catalog.values()):
            if folder and _folder_of(entry.path) != folder:
                continue
            note = await self._engine.read_note(entry.path)
            if _is_meta(note):
                continue
            summaries.append(_note_to_summary(note))
        summaries.sort(key=lambda s: s.permalink)
        return summaries

    async def recent_activity(self, *, limit: int = 10) -> list[NoteSummary]:
        entries = sorted(
            self._engine.catalog.values(), key=lambda entry: entry.mtime_ns, reverse=True
        )
        summaries: list[NoteSummary] = []
        for entry in entries:
            if len(summaries) >= limit:
                break
            note = await self._engine.read_note(entry.path)
            if _is_meta(note):
                continue
            summaries.append(_note_to_summary(note))
        return summaries


if TYPE_CHECKING:
    # Static-only check (never executed): EngineVaultService must satisfy
    # the VaultService protocol exactly like FakeVaultService does.
    _typecheck: VaultService = EngineVaultService(cast(VaultEngine, None))

__all__ = ["EngineVaultService"]
