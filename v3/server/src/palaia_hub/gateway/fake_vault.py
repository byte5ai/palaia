"""An in-memory :class:`VaultService` for tests and the e2e connectivity check.

This is deliberately not a vault-format-conformant engine — no files, no git,
no frontmatter parsing. It exists so the gateway's tool family (this SPEC)
can be built and tested end-to-end without depending on SPEC-102, which runs
in parallel and is not merged. SPEC-113 replaces this with a real adapter
over the vault engine; nothing here is meant to survive that swap.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from . import inbox as inbox_shape
from .vault_protocol import (
    CaptureResult,
    InboxStatusResult,
    NoteRecord,
    NoteSummary,
    SearchHit,
    VaultServiceError,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.lower()).strip("-")
    return slug or "note"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class FakeVaultService:
    """Stores notes in a dict keyed by permalink. Not thread-safe; test-only."""

    def __init__(self) -> None:
        self._notes: dict[str, NoteRecord] = {}

    def seed(self, note: NoteRecord) -> None:
        """Directly insert a note (fixture setup helper, bypasses write())."""
        self._notes[note.permalink] = note

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        needle = query.lower()
        hits: list[SearchHit] = []
        for note in self._notes.values():
            haystack = f"{note.title}\n{note.body}".lower()
            if needle in haystack:
                idx = haystack.find(needle)
                start = max(0, idx - 20)
                snippet = note.body[start : start + len(query) + 40].strip()
                hits.append(
                    SearchHit(
                        permalink=note.permalink,
                        title=note.title,
                        snippet=snippet,
                        score=1.0 if needle in note.title.lower() else 0.5,
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def read(self, permalink: str) -> NoteRecord:
        note = self._notes.get(permalink)
        if note is None:
            raise VaultServiceError(f"no note at permalink '{permalink}'")
        return note

    async def write(
        self,
        title: str,
        body: str,
        *,
        folder: str = "",
        type: str = "note",  # noqa: A002
        tags: list[str] | None = None,
    ) -> NoteRecord:
        folder = folder.strip("/")
        permalink = f"{folder}/{_slugify(title)}" if folder else _slugify(title)
        if permalink in self._notes:
            raise VaultServiceError(
                f"a note already exists at permalink '{permalink}' "
                "(fake vault has no dedup/merge; use edit instead)"
            )
        now = _now()
        note = NoteRecord(
            permalink=permalink,
            title=title,
            type=type,
            tags=list(tags or []),
            folder=folder,
            body=body,
            created=now,
            modified=now,
        )
        self._notes[permalink] = note
        return note

    async def edit(
        self,
        permalink: str,
        *,
        body: str | None = None,
        append: str | None = None,
        tags: list[str] | None = None,
    ) -> NoteRecord:
        note = await self.read(permalink)
        new_body = note.body
        if body is not None:
            new_body = body
        if append is not None:
            new_body = f"{new_body}\n{append}" if new_body else append
        updated = note.model_copy(
            update={
                "body": new_body,
                "tags": list(tags) if tags is not None else note.tags,
                "modified": _now(),
            }
        )
        self._notes[permalink] = updated
        return updated

    async def move(self, permalink: str, folder: str) -> NoteRecord:
        note = await self.read(permalink)
        updated = note.model_copy(update={"folder": folder.strip("/"), "modified": _now()})
        self._notes[permalink] = updated
        return updated

    async def delete(self, permalink: str) -> bool:
        return self._notes.pop(permalink, None) is not None

    async def list_notes(self, *, folder: str = "") -> list[NoteSummary]:
        folder = folder.strip("/")
        notes = [
            NoteSummary(**note.model_dump(exclude={"body", "created"}))
            for note in self._notes.values()
            if not folder or note.folder == folder
        ]
        notes.sort(key=lambda n: n.permalink)
        return notes

    async def recent_activity(self, *, limit: int = 10) -> list[NoteSummary]:
        notes = sorted(self._notes.values(), key=lambda n: n.modified, reverse=True)
        return [
            NoteSummary(**note.model_dump(exclude={"body", "created"})) for note in notes[:limit]
        ]

    def _inbox_notes(self) -> list[NoteRecord]:
        return [note for note in self._notes.values() if note.folder == "inbox"]

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

        for existing in self._inbox_notes():
            if inbox_shape.extract_capture_hash(existing.body) == content_hash:
                return CaptureResult(
                    permalink=existing.permalink,
                    title=existing.title,
                    capture_id=existing.capture_id,
                    status=existing.status,
                    duplicate=True,
                )

        resolved_source = (source or "").strip() or inbox_shape.default_source()
        slug = _slugify(what_it_concerns)
        permalink = f"inbox/{slug}"
        suffix = 2
        while permalink in self._notes:
            permalink = f"inbox/{slug}-{suffix}"
            suffix += 1
        capture_id = inbox_shape.capture_id_for(permalink)
        body = inbox_shape.compose_capture_body(
            what_it_concerns=what_it_concerns,
            why_keep=why_keep,
            content=content,
            source=resolved_source,
            content_hash=content_hash,
        )
        now = _now()
        note = NoteRecord(
            permalink=permalink,
            title=what_it_concerns,
            type="capture",
            tags=["inbox"],
            folder="inbox",
            status="uncurated",
            capture_id=capture_id,
            body=body,
            created=now,
            modified=now,
        )
        self._notes[permalink] = note
        return CaptureResult(
            permalink=permalink, title=note.title, capture_id=capture_id, status="uncurated"
        )

    async def inbox_status(self) -> InboxStatusResult:
        captures = [note for note in self._inbox_notes() if note.status == "uncurated"]
        if not captures:
            return InboxStatusResult(count=0)
        captures.sort(key=lambda n: n.created)
        oldest = captures[0]
        newest = max(captures, key=lambda n: n.created)
        now = datetime.now(UTC)
        oldest_created = datetime.fromisoformat(oldest.created.replace("Z", "+00:00"))
        age = (now - oldest_created).total_seconds()
        return InboxStatusResult(
            count=len(captures),
            oldest_capture_id=oldest.capture_id,
            oldest_age_seconds=max(age, 0.0),
            last_capture_id=newest.capture_id,
            last_captured_at=newest.created,
        )
