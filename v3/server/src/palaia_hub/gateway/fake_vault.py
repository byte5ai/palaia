"""An in-memory :class:`VaultService` for tests and the e2e connectivity check.

This is deliberately not a vault-format-conformant engine — no files, no git,
no index. It exists so the gateway's tool family (this SPEC)
can be built and tested end-to-end without depending on SPEC-102, which runs
in parallel and is not merged. SPEC-113 replaces this with a real adapter
over the vault engine; nothing here is meant to survive that swap.

SPEC-106's ``recall``/``build_context`` are implemented here too, in the same
spirit: real enough to exercise the *tool surface* (dual output, parameter
aliases, error results) without an index. They reuse the pure halves of
:mod:`palaia_hub.recall` — the body grammar parser for observations and
relations, variant resolution, value-reference resolution, the graph walk and
the token budget — and skip exactly the parts that need an index: **decay
scoring** (no timestamps worth ranking, no access counters) and hybrid
search. Ordering here is retrieval order; the real adapter's is decay-ranked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from palaia_hub.recall import budget as bg
from palaia_hub.recall.embeds import SourceNote, resolve_references
from palaia_hub.recall.models import (
    ContextNode,
    ContextResult,
    RecallEntry,
    RecallObservation,
    RecallResult,
)
from palaia_hub.recall.ranking import relevance_of
from palaia_hub.recall.service import context_header
from palaia_hub.recall.traversal import (
    DEFAULT_DEPTH,
    GraphView,
    clamp_depth,
    parse_timeframe,
    walk,
)
from palaia_hub.recall.variants import (
    ModelScope,
    dropped_indices,
    parse_model_scope,
    resolve_variants,
)
from palaia_hub.vault.parse import ParsedNote, Relation, parse_note

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

    # -------------------------------------------------------- review (SPEC-208)

    def _review_proposals(self) -> list[NoteRecord]:
        return [
            note
            for note in self._notes.values()
            if note.folder == "review" and note.type == "proposal"
        ]

    async def review_queue(self) -> ReviewQueueResult:
        proposals = [
            ProposalSummary(
                permalink=note.permalink,
                title=note.title,
                status=note.status,
                created=note.created,
                body=note.body,
            )
            for note in self._review_proposals()
        ]
        proposals.sort(key=lambda p: p.created or p.permalink)
        return ReviewQueueResult(proposals=proposals)

    async def review_decide(self, permalink: str, decision: str) -> ReviewDecideResult:
        note = await self.read(permalink)
        if note.type != "proposal":
            raise VaultServiceError(f"{permalink!r} is not a review proposal")
        if note.status != "proposed":
            raise VaultServiceError(
                f"proposal {permalink!r} is not awaiting review "
                f"(status: {note.status!r}, expected 'proposed')"
            )
        updated = note.model_copy(update={"status": decision, "modified": _now()})
        self._notes[permalink] = updated
        return ReviewDecideResult(permalink=permalink, status=decision)

    # -------------------------------------------------------- recall (SPEC-106)

    def _parsed(self, permalink: str, body: str) -> ParsedNote:
        # A leading newline so a body starting with "---" cannot be re-read as
        # frontmatter; body line n is therefore parse line n + 2 — the same
        # convention palaia_hub.recall.service uses.
        return parse_note("\n" + body, f"{permalink}.md")

    def note_at(self, permalink: str) -> NoteRecord | None:
        """The note stored under exactly this permalink, or ``None``."""
        return self._notes.get(permalink)

    def permalinks(self) -> tuple[str, ...]:
        """Every stored permalink."""
        return tuple(self._notes)

    def relations_of(self, permalink: str) -> tuple[Relation, ...]:
        """The relation lines in one note's body (format spec §5.2)."""
        note = self._notes.get(permalink)
        if note is None:
            return ()
        return self._parsed(note.permalink, note.body).relations

    def lookup(self, target: str) -> NoteRecord | None:
        """Resolve an embed/relation target: permalink, then title, then slug."""
        key = target.strip().removeprefix("memory://").strip("/")
        if key in self._notes:
            return self._notes[key]
        folded = key.casefold()
        for note in self._notes.values():
            if note.title.casefold() == folded:
                return note
        slug = _slugify(key)
        for note in self._notes.values():
            if note.permalink.rsplit("/", 1)[-1] == slug:
                return note
        return None

    def _filter_variants(self, body: str, caller: ModelScope) -> str:
        if "|" not in body:
            return body
        observations = self._parsed("variants", body).observations
        if not observations:
            return body
        dropped = {observations[index].line - 2 for index in dropped_indices(observations, caller)}
        return "\n".join(
            line for index, line in enumerate(body.split("\n")) if index not in dropped
        )

    def _resolved_body(self, note: NoteRecord, caller: ModelScope) -> tuple[str, list[str]]:
        resolved = resolve_references(
            self._filter_variants(note.body, caller),
            entry=SourceNote(permalink=note.permalink, title=note.title, body=note.body),
            source=_FakeNoteSource(self),
            transform=lambda text: self._filter_variants(text, caller),
        )
        return resolved.text, [str(warning) for warning in resolved.warnings]

    def _observations(self, note: NoteRecord, caller: ModelScope) -> list[RecallObservation]:
        served = resolve_variants(self._parsed(note.permalink, note.body).observations, caller)
        return [
            RecallObservation(
                ref=f"{note.permalink}/obs/{_slugify(obs.category)}",
                category=obs.category,
                scope=obs.scope,
                text=obs.text,
                context=obs.context,
                block_id=obs.block_id,
                tags=list(obs.tags),
            )
            for obs in served
        ]

    def _candidates(self, *, query: str, ref: str) -> list[NoteRecord]:
        if ref.strip():
            note = self.lookup(ref)
            if note is None:
                raise VaultServiceError(
                    f"nothing in this vault matches '{ref}' (resolution order: "
                    f"permalink, title, slug)"
                )
            return [note]
        if not query.strip():
            raise VaultServiceError(
                "recall needs something to start from. Fix: pass a query (what "
                "you are looking for) or a ref (a memory:// address)."
            )
        return _substring_hits(self._notes.values(), query)

    async def recall(
        self,
        *,
        query: str = "",
        ref: str = "",
        limit: int = 5,
        model: str = "",
    ) -> RecallResult:
        caller = parse_model_scope(model)
        candidates = self._candidates(query=query, ref=ref)
        entries: list[RecallEntry] = []
        warnings: list[str] = []
        for rank, note in enumerate(candidates[: max(1, int(limit))]):
            body, note_warnings = self._resolved_body(note, caller)
            warnings.extend(note_warnings)
            entries.append(
                RecallEntry(
                    ref=note.permalink,
                    permalink=note.permalink,
                    title=note.title,
                    type=note.type,
                    kind="note",
                    snippet=bg.elide(note.body, 160),
                    score=round(relevance_of(rank), 9),
                    relevance_rank=rank,
                    body=body,
                    observations=self._observations(note, caller),
                    warnings=note_warnings,
                )
            )
        return RecallResult(
            query=query,
            ref=ref,
            model=str(caller) if caller.known else "",
            entries=entries,
            matched=len(candidates),
            warnings=warnings,
        )

    async def build_context(
        self,
        *,
        ref: str = "",
        query: str = "",
        depth: int = DEFAULT_DEPTH,
        timeframe: str = "",
        max_tokens: int = bg.DEFAULT_MAX_TOKENS,
        model: str = "",
    ) -> ContextResult:
        caller = parse_model_scope(model)
        seeds = [note.permalink for note in self._candidates(query=query, ref=ref)][:3]
        hops = clamp_depth(depth)
        result = walk(
            _FakeGraphView(self),
            seeds,
            depth=hops,
            since=parse_timeframe(timeframe, now=datetime.now(UTC)),
        )
        header = context_header(seeds, query=query, depth=hops)
        items: list[bg.BudgetItem] = []
        extras: dict[str, tuple[list[str], list[RecallObservation]]] = {}
        for node in result.nodes:
            note = self._notes.get(node.permalink)
            if note is None:
                continue
            heading = f"## {note.title} — memory://{note.permalink} [{note.type}]"
            if not node.is_seed:
                heading += f"\n> depth {node.depth} · {node.via} {node.parent}"
            body, note_warnings = self._resolved_body(note, caller)
            observations = self._observations(note, caller)
            summary_lines = [
                f"- [{obs.category}] {obs.text}"
                for obs in observations[: bg.SUMMARY_OBSERVATIONS]
            ]
            summary = (
                "\n".join([heading, "(summarized to fit the token budget)", *summary_lines]) + "\n"
                if summary_lines
                else ""
            )
            extras[node.permalink] = (note_warnings, observations)
            items.append(
                bg.BudgetItem(
                    key=node.permalink,
                    full=f"{heading}\n{body.strip()}\n" if body.strip() else f"{heading}\n",
                    summary=summary,
                    stub=f"{bg.stub_line(note.title, note.permalink)}\n",
                )
            )
        plan = bg.plan_budget(items, max_tokens=max_tokens, overhead=header)
        by_permalink = {node.permalink: node for node in result.nodes}
        nodes: list[ContextNode] = []
        warnings: list[str] = []
        for placement in plan.placements:
            node = by_permalink[placement.key]
            note = self._notes[placement.key]
            note_warnings, observations = extras[placement.key]
            full = placement.tier == "full"
            if full:
                warnings.extend(note_warnings)
            nodes.append(
                ContextNode(
                    ref=placement.key,
                    permalink=placement.key,
                    title=note.title,
                    type=note.type,
                    depth=node.depth,
                    via=node.via,
                    parent=node.parent,
                    tier=placement.tier,
                    tokens=placement.tokens,
                    text=placement.text,
                    observations=[] if full else observations,
                    warnings=note_warnings if full else [],
                )
            )
        return ContextResult(
            seeds=seeds,
            query=query,
            model=str(caller) if caller.known else "",
            depth=hops,
            timeframe=timeframe,
            max_tokens=plan.budget,
            requested_max_tokens=int(max_tokens),
            estimated_tokens=plan.tokens,
            nodes=nodes,
            dropped=list(plan.dropped),
            walk_truncated=result.truncated,
            skipped_by_timeframe=result.skipped_by_timeframe,
            degraded=plan.degraded,
            warnings=warnings,
        )


def _substring_hits(notes: Iterable[NoteRecord], query: str) -> list[NoteRecord]:
    """Substring match over ``notes``, title hits first — the fake's retrieval."""
    needle = query.casefold()
    scored: list[tuple[int, str, NoteRecord]] = []
    for note in notes:
        if needle not in f"{note.title}\n{note.body}".casefold():
            continue
        scored.append((0 if needle in note.title.casefold() else 1, note.permalink, note))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [note for _, _, note in scored]


@dataclass(frozen=True, slots=True)
class _FakeEdge:
    """A relation between two fake notes, shaped like the index's ``Edge``."""

    target: str
    type: str
    direction: str

    @property
    def label(self) -> str:
        return f"{self.type} →" if self.direction == "out" else f"← {self.type}"


class _FakeNoteSource:
    """A :class:`~palaia_hub.recall.NoteSource` over the fake's dict of notes."""

    def __init__(self, vault: FakeVaultService) -> None:
        self._vault = vault

    def resolve(self, target: str) -> SourceNote | None:
        note = self._vault.lookup(target)
        if note is None:
            return None
        return SourceNote(permalink=note.permalink, title=note.title, body=note.body)


class _FakeGraphView:
    """A :class:`~palaia_hub.recall.traversal.GraphView` over the fake's notes.

    Relations are re-parsed from bodies on every call — fine for a handful of
    test notes, and it keeps the fake from having to maintain a graph.
    """

    def __init__(self, vault: FakeVaultService) -> None:
        self._vault = vault

    def neighbors(self, permalink: str) -> Sequence[_FakeEdge]:
        edges: list[_FakeEdge] = []
        seen: set[tuple[str, str, str]] = set()

        def add(other: str, relation_type: str, direction: str) -> None:
            if other == permalink:
                return
            key = (other, relation_type, direction)
            if key in seen:
                return
            seen.add(key)
            edges.append(_FakeEdge(other, relation_type, direction))

        for relation in self._vault.relations_of(permalink):
            target = self._vault.lookup(relation.target)
            if target is not None:
                add(target.permalink, relation.type, "out")
        for other in sorted(self._vault.permalinks()):
            for relation in self._vault.relations_of(other):
                target = self._vault.lookup(relation.target)
                if target is not None and target.permalink == permalink:
                    add(other, relation.type, "in")
        return edges

    def note(self, permalink: str) -> NoteRecord | None:
        return self._vault.note_at(permalink)


if TYPE_CHECKING:
    # Static-only (never executed): the fake must satisfy the same protocol
    # the real adapter does, so a protocol change breaks the build here
    # instead of at the first test that calls the missing method.
    _typecheck: VaultService = FakeVaultService()
    _view: GraphView = _FakeGraphView(FakeVaultService())
