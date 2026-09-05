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

**Search** is index-backed when a :class:`~palaia_hub.index.VaultIndex` is
passed in (SPEC-104): the tool's query runs as a hybrid FTS+vector query and
degrades to FTS while the embed backlog drains. Without an index the adapter
keeps its original linear substring scan — SPEC-105's trade-off — so every
caller that has not been taught about the index (and every test that wants
search with no SQLite file on disk) still works unchanged.

**Recall** (SPEC-106) needs that index unconditionally: identity resolution,
the relation graph, the access counters and note bodies all live there. An
adapter built without one answers ``recall``/``build_context`` with a
tool-level error naming the omission, rather than degrading into a worse
answer that looks like a real one.

The ``ranking`` argument is where the hub's configured decay weights arrive —
``EngineVaultService(engine, index, ranking=weights_from_settings(
config.recall))``, with ``weights_from_settings`` from
:mod:`palaia_hub.recall.ranking` and ``config.recall`` the ``recall:`` section
of ``config.yaml``. Omitting it uses
:data:`~palaia_hub.recall.DEFAULT_WEIGHTS`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from palaia_hub.events.schema import HubEventHook
from palaia_hub.index import SearchFilters, VaultIndex
from palaia_hub.recall import DEFAULT_WEIGHTS, RankingWeights
from palaia_hub.recall.budget import DEFAULT_MAX_TOKENS
from palaia_hub.recall.models import ContextResult, RecallResult
from palaia_hub.recall.service import CALLER_ERRORS as _RECALL_CALLER_ERRORS
from palaia_hub.recall.service import DEFAULT_RECALL_LIMIT, RecallService
from palaia_hub.recall.traversal import DEFAULT_DEPTH
from palaia_hub.vault import (
    AmbiguousReferenceError,
    ChecksumConflictError,
    InvalidPathError,
    MalformedFrontmatterError,
    Note,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    UncommittedWriteError,
    VaultEngine,
    VolatileNameError,
)
from palaia_hub.vault import permalink as pl

from . import inbox as inbox_shape
from .vault_protocol import (
    CaptureResult,
    InboxStatusResult,
    NoteRecord,
    NoteSummary,
    ProposalSummary,
    ReviewDecideResult,
    ReviewQueueResult,
    SearchHit,
    VaultService,
    VaultServiceError,
)

logger = logging.getLogger("palaia_hub.gateway.wiring")

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
    MalformedFrontmatterError,
    NoteExistsError,
    NoteNotFoundError,
    PermalinkConflictError,
    UncommittedWriteError,
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


def _age_seconds(created_iso: str) -> float:
    """Seconds since ``created_iso``; 0.0 when the timestamp is absent/unparseable."""
    if not created_iso:
        return 0.0
    try:
        created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max((datetime.now(UTC) - created).total_seconds(), 0.0)


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
        # `status`/`capture_id` are format-spec §2.1 schema keys "relevant
        # beyond captures" (see NoteSummary's own field comment) — SPEC-208
        # is the first caller that needs a non-capture note's status (a
        # review/ proposal's `proposed`/`approved`/`rejected`/...), so this
        # is populated generically here rather than only where SPEC-107's
        # capture/inbox_status methods construct a result by hand.
        status=str(frontmatter.get("status") or ""),
        capture_id=str(frontmatter.get("capture_id") or ""),
        body=note.body,
    )


def _note_to_summary(note: Note) -> NoteSummary:
    record = _note_to_record(note)
    return NoteSummary(
        **record.model_dump(
            exclude={"body", "created", "resolved_body", "resolution_warnings"}
        )
    )


class EngineVaultService:
    """:class:`VaultService` over one open :class:`~palaia_hub.vault.VaultEngine`.

    The engine must already be opened (``await engine.open(...)``) — this
    adapter does not manage the engine's lifecycle, only translates calls.
    The same goes for ``index``: pass an already-opened
    :class:`~palaia_hub.index.VaultIndex` to get indexed + hybrid search.

    ``on_event`` is SPEC-201's ``inbox.captured`` hook point: given, called
    after every ``capture()`` (including a duplicate-acknowledged one) with
    ``("inbox.captured", {...})`` — see :data:`~palaia_hub.events.schema.
    HubEventHook`. Omitted (the default), ``capture()`` behaves exactly as
    before this parameter existed.
    """

    def __init__(
        self,
        engine: VaultEngine,
        index: VaultIndex | None = None,
        *,
        ranking: RankingWeights = DEFAULT_WEIGHTS,
        on_event: HubEventHook | None = None,
    ) -> None:
        self._engine = engine
        self._index = index
        #: SPEC-201's ``inbox.captured`` hook point — see :data:`HubEventHook`.
        self._on_event = on_event
        # SPEC-106's recall layer works entirely off the index (identity
        # lookups, the relation graph, access counters and note bodies all
        # live there), so it exists only when an index does — see
        # `_recall_service` for what an index-less adapter answers instead.
        self._recall = (
            RecallService(index, vault=engine.name, weights=ranking)
            if index is not None
            else None
        )

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if self._index is not None:
            return await self._indexed_search(query, limit=limit)
        return await self._scan_search(query, limit=limit)

    async def _indexed_search(self, query: str, *, limit: int) -> list[SearchHit]:
        """Hybrid search through the SPEC-104 index.

        ``meta`` notes are excluded here rather than filtered afterwards
        (format spec §6: meta is "excluded from normal recall"), so the
        requested ``limit`` is a limit on results the caller can use.

        The index addresses hits below note granularity (an observation's
        synthetic permalink, §9.2). The MCP-visible :class:`SearchHit` stays
        note-level on purpose — that is the tool contract SPEC-105 froze and
        SPEC-113 snapshots — so a sub-note hit reports its note's permalink
        and lets its snippet carry the matched line.
        """
        assert self._index is not None
        results = await self._index.search(
            query,
            mode="hybrid",
            limit=limit,
            filters=SearchFilters(exclude_types=("meta",)),
        )
        return [
            SearchHit(
                permalink=hit.permalink,
                title=hit.title,
                snippet=hit.snippet,
                score=round(hit.score, 6),
            )
            for hit in results.hits
        ]

    async def _scan_search(self, query: str, *, limit: int) -> list[SearchHit]:
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
        record = _note_to_record(note)
        return await self._with_resolved_body(record)

    async def _with_resolved_body(self, record: NoteRecord) -> NoteRecord:
        """Attach the embed-resolved body, when there is an index to resolve with.

        Resolution failures are deliberately swallowed: ``read`` answering
        with the note as written is strictly better than ``read`` failing
        because one value reference in it is broken (and §5.3's markers mean
        a *resolvable* problem never raises in the first place).
        """
        if self._recall is None:
            return record
        try:
            resolved = await self._recall.resolved_body(record.permalink)
        except Exception:  # noqa: BLE001 - never fail a read over a reference
            return record
        if resolved.text == record.body or resolved.text.strip() == record.body.strip():
            return record
        return record.model_copy(
            update={
                "resolved_body": resolved.text,
                "resolution_warnings": [str(warning) for warning in resolved.warnings],
            }
        )

    # ----------------------------------------------------------------- recall

    def _recall_service(self) -> RecallService:
        if self._recall is None:
            raise VaultServiceError(
                "recall needs this vault's search index, and none is attached. "
                "Fix: open a VaultIndex for the vault and pass it to "
                "EngineVaultService(engine, index)."
            )
        return self._recall

    async def recall(
        self,
        *,
        query: str = "",
        ref: str = "",
        limit: int = DEFAULT_RECALL_LIMIT,
        model: str = "",
    ) -> RecallResult:
        service = self._recall_service()
        try:
            return await service.recall(query=query, ref=ref, limit=limit, model=model)
        except _RECALL_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc

    async def build_context(
        self,
        *,
        ref: str = "",
        query: str = "",
        depth: int = DEFAULT_DEPTH,
        timeframe: str = "",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model: str = "",
    ) -> ContextResult:
        service = self._recall_service()
        try:
            return await service.build_context(
                ref=ref,
                query=query,
                depth=depth,
                timeframe=timeframe,
                max_tokens=max_tokens,
                model=model,
            )
        except _RECALL_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc

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

    async def capture(
        self,
        *,
        what_it_concerns: str,
        why_keep: str,
        content: str,
        source: str | None = None,
    ) -> CaptureResult:
        what_it_concerns = what_it_concerns.strip()
        why_keep = why_keep.strip()
        content = content.strip()
        content_hash = inbox_shape.content_hash_for(what_it_concerns, why_keep, content)

        resolved_source = (source or "").strip() or inbox_shape.default_source()

        # Dedup guard (format spec §7): an identical capture is acked, not duplicated.
        for existing in await self._inbox_captures():
            existing_hash = inbox_shape.extract_capture_hash(existing.body)
            if existing_hash == content_hash:
                fm_status = str(existing.frontmatter.get("status") or "uncurated")
                duplicate_result = CaptureResult(
                    permalink=existing.permalink or existing.path,
                    title=existing.title,
                    capture_id=str(existing.frontmatter.get("capture_id") or ""),
                    status=fm_status,
                    duplicate=True,
                )
                self._emit_captured(duplicate_result, source=resolved_source)
                return duplicate_result

        slug = pl.slugify(what_it_concerns) or "capture"
        relative = f"inbox/{slug}.md"
        suffix = 2
        while self._path_exists(relative):
            relative = f"inbox/{slug}-{suffix}.md"
            suffix += 1
        permalink = relative[: -len(".md")]
        capture_id = inbox_shape.capture_id_for(permalink)
        body = inbox_shape.compose_capture_body(
            what_it_concerns=what_it_concerns,
            why_keep=why_keep,
            content=content,
            source=resolved_source,
            content_hash=content_hash,
        )
        frontmatter = dict(inbox_shape.capture_frontmatter(capture_id=capture_id))
        try:
            result = await self._engine.write_note(
                relative,
                body=body,
                title=what_it_concerns,
                frontmatter=frontmatter,
                must_create=True,
            )
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        assert result.note is not None
        captured = CaptureResult(
            permalink=result.note.permalink or permalink,
            title=result.note.title,
            capture_id=capture_id,
            status="uncurated",
        )
        self._emit_captured(captured, source=resolved_source)
        return captured

    def _emit_captured(self, result: CaptureResult, *, source: str) -> None:
        """SPEC-201's ``inbox.captured`` hook point — see :data:`HubEventHook`."""
        if self._on_event is None:
            return
        try:
            self._on_event(
                "inbox.captured",
                {
                    "vault": self._engine.name,
                    "permalink": result.permalink,
                    "capture_id": result.capture_id,
                    "title": result.title,
                    "source": source,
                    "duplicate": result.duplicate,
                },
            )
        except Exception:  # noqa: BLE001 - a hook must not break a capture
            logger.exception("inbox.captured hook failed")

    async def inbox_status(self) -> InboxStatusResult:
        captures = [
            note
            for note in await self._inbox_captures()
            if str(note.frontmatter.get("status") or "") == "uncurated"
        ]
        if not captures:
            return InboxStatusResult(count=0)

        def created_of(note: Note) -> str:
            return str(note.frontmatter.get("created") or "")

        captures.sort(key=created_of)
        oldest, newest = captures[0], captures[-1]
        oldest_age = _age_seconds(created_of(oldest))
        return InboxStatusResult(
            count=len(captures),
            oldest_capture_id=str(oldest.frontmatter.get("capture_id") or ""),
            oldest_age_seconds=oldest_age,
            last_capture_id=str(newest.frontmatter.get("capture_id") or ""),
            last_captured_at=created_of(newest),
        )

    async def _inbox_captures(self) -> list[Note]:
        notes: list[Note] = []
        for entry in list(self._engine.catalog.values()):
            if not entry.path.startswith("inbox/"):
                continue
            note = await self._engine.read_note(entry.path)
            if str(note.frontmatter.get("type", "note")) == "capture":
                notes.append(note)
        return notes

    def _path_exists(self, relative: str) -> bool:
        return any(entry.path == relative for entry in self._engine.catalog.values())

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

    # ------------------------------------------------------- review (SPEC-208)

    async def _review_proposals(self) -> list[Note]:
        notes: list[Note] = []
        for entry in list(self._engine.catalog.values()):
            if not entry.path.startswith("review/"):
                continue
            note = await self._engine.read_note(entry.path)
            if str(note.frontmatter.get("type", "note")) == "proposal":
                notes.append(note)
        return notes

    async def review_queue(self) -> ReviewQueueResult:
        proposals = [
            ProposalSummary(
                permalink=note.permalink or note.path,
                title=note.title,
                status=str(note.frontmatter.get("status") or ""),
                created=str(note.frontmatter.get("created") or ""),
                body=note.body,
            )
            for note in await self._review_proposals()
        ]
        proposals.sort(key=lambda p: p.created or p.permalink)
        return ReviewQueueResult(proposals=proposals)

    async def review_decide(self, permalink: str, decision: str) -> ReviewDecideResult:
        try:
            current = await self._engine.read_note(permalink)
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        if str(current.frontmatter.get("type", "note")) != "proposal":
            raise VaultServiceError(f"{permalink!r} is not a review proposal")
        current_status = str(current.frontmatter.get("status") or "")
        if current_status != "proposed":
            raise VaultServiceError(
                f"proposal {permalink!r} is not awaiting review "
                f"(status: {current_status!r}, expected 'proposed')"
            )
        try:
            result = await self._engine.edit_note(
                permalink,
                frontmatter={"status": decision},
                expected_checksum=current.checksum,
            )
        except _ENGINE_CALLER_ERRORS as exc:
            raise VaultServiceError(str(exc)) from exc
        assert result.note is not None
        return ReviewDecideResult(
            permalink=result.note.permalink or permalink, status=decision
        )


if TYPE_CHECKING:
    # Static-only check (never executed): EngineVaultService must satisfy
    # the VaultService protocol exactly like FakeVaultService does.
    _typecheck: VaultService = EngineVaultService(cast(VaultEngine, None))

__all__ = ["EngineVaultService"]
