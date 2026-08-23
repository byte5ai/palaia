"""``RecallService`` — the intelligence layer, assembled.

One object over one vault's index, with two entry points:

* :meth:`RecallService.recall` — resolve a ``memory://`` reference, or run a
  query through SPEC-104's hybrid search, then decay-rank the candidates,
  resolve each entry's per-model variants and value references, and answer.
* :meth:`RecallService.build_context` — the same starting points, but walk
  the relation graph from there and fit the result into a token budget.

Nothing here reimplements search: retrieval is
:meth:`palaia_hub.index.VaultIndex.search`, and this module's job is
everything that happens to its *output* (plus everything a reference-based
call needs, which search never sees at all).

**Search depth vs. answer limit.** A query fetches
:data:`CANDIDATE_DEPTH_FACTOR` × ``limit`` candidates and returns ``limit``
of them *after* decay scoring. Ranking the exact page the caller asked for
would make decay a no-op on the boundary — the whole point is that a
slightly-less-literal but far fresher or more load-bearing note can climb
into the answer.

**Access counters are written after ranking, never before** (see
:meth:`palaia_hub.index.GraphReader.record_access`), so the same call twice
against an unchanged vault ranks identically.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from palaia_hub.index import GraphReader, IndexedNote, SearchFilters, VaultIndex
from palaia_hub.vault.errors import AmbiguousReferenceError, NoteNotFoundError, VaultError
from palaia_hub.vault.parse import parse_note

from . import budget as bg
from .embeds import NoteSource, ResolvedText, SourceNote, resolve_references
from .models import (
    ContextNode,
    ContextResult,
    RecallEntry,
    RecallObservation,
    RecallResult,
)
from .ranking import (
    DEFAULT_WEIGHTS,
    Candidate,
    RankedRef,
    RankingWeights,
    decay_factors,
    rank_candidates,
)
from .refs import MemoryResolver, ResolvedRef
from .traversal import (
    DEFAULT_DEPTH,
    DEFAULT_MAX_NODES,
    WalkNode,
    clamp_depth,
    parse_timeframe,
    walk,
)
from .variants import ModelScope, dropped_indices, parse_model_scope, resolve_variants

logger = logging.getLogger("palaia_hub.recall.service")

#: Candidates fetched per requested result before decay scoring reorders them.
CANDIDATE_DEPTH_FACTOR = 4

#: Floor on that fetch, so a ``limit=1`` call still gives decay something to
#: choose between.
CANDIDATE_MIN_DEPTH = 20

#: Default results per ``recall`` call. Small on purpose: recall returns
#: resolved bodies, and five notes is already a substantial read.
DEFAULT_RECALL_LIMIT = 5

#: How many query hits seed a ``build_context`` walk. The graph does the
#: broadening from there — seeding it with twenty hits would produce a
#: neighborhood, not a context.
DEFAULT_SEED_LIMIT = 3

#: Entry types normal recall never volunteers (format spec §6: ``meta`` is
#: vault self-description, "excluded from normal recall"). A caller naming a
#: meta note by reference still gets it — this filter is on *retrieval*.
_EXCLUDED_TYPES: tuple[str, ...] = ("meta",)


class RecallError(ValueError):
    """A caller-facing recall failure (no starting point, unusable arguments)."""


class _IndexNoteSource:
    """:class:`~.embeds.NoteSource` over one vault's index, with a per-call cache.

    An ambiguous embed target resolves to ``None`` (rendering
    ``⟦missing: …⟧``) rather than raising: an embed is a *value reference*
    inside someone's prose, and failing an entire recall because one
    reference is ambiguous would be the wrong trade. The ambiguity is still
    discoverable — resolving the same target through ``recall``'s ``ref``
    parameter reports it with candidates listed.
    """

    def __init__(self, resolver: MemoryResolver, graph: GraphReader) -> None:
        self._resolver = resolver
        self._graph = graph
        self._cache: dict[str, SourceNote | None] = {}

    def resolve(self, target: str) -> SourceNote | None:
        key = target.strip().casefold()
        if key in self._cache:
            return self._cache[key]
        resolved: SourceNote | None = None
        try:
            matches = self._resolver.resolve(target)
        except (AmbiguousReferenceError, NoteNotFoundError):
            matches = []
        if len(matches) == 1:
            note = self._graph.note(matches[0].permalink)
            if note is not None:
                resolved = SourceNote(
                    permalink=note.permalink, title=note.title, body=note.body
                )
        self._cache[key] = resolved
        return resolved


class RecallService:
    """Recall, traversal and context assembly over one :class:`VaultIndex`."""

    def __init__(
        self,
        index: VaultIndex,
        *,
        vault: str = "",
        weights: RankingWeights = DEFAULT_WEIGHTS,
        track_access: bool = True,
        clock: Callable[[], datetime] | None = None,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> None:
        self._index = index
        self._graph = index.graph
        self._resolver = MemoryResolver(index.graph, vault=vault)
        self._weights = weights
        self._track_access = track_access
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_nodes = max_nodes

    # ------------------------------------------------------------------ public

    @property
    def resolver(self) -> MemoryResolver:
        """The ``memory://`` resolver, for callers that only need addressing."""
        return self._resolver

    async def recall(
        self,
        *,
        query: str = "",
        ref: str = "",
        limit: int = DEFAULT_RECALL_LIMIT,
        model: str = "",
        include_body: bool = True,
    ) -> RecallResult:
        """Recall by reference or by query, decay-ranked and fully resolved.

        ``ref`` wins when both are given: a caller who names an address has
        already decided, and re-ranking their choice against a query would
        answer a question they did not ask.
        """
        limit = max(1, int(limit))
        caller = parse_model_scope(model)
        if ref.strip():
            candidates = await asyncio.to_thread(self._candidates_from_ref, ref)
            degraded, reason = False, ""
        elif query.strip():
            candidates, degraded, reason = await self._candidates_from_query(query, limit=limit)
        else:
            raise RecallError(
                "recall needs something to start from. Fix: pass a query "
                "(what you are looking for) or a ref (a memory:// address)."
            )
        return await asyncio.to_thread(
            self._finish_recall,
            candidates,
            query=query,
            ref=ref,
            caller=caller,
            limit=limit,
            include_body=include_body,
            degraded=degraded,
            degraded_reason=reason,
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
        seed_limit: int = DEFAULT_SEED_LIMIT,
    ) -> ContextResult:
        """Assemble a budgeted context package around ``ref`` or ``query``."""
        caller = parse_model_scope(model)
        warnings: list[str] = []
        if ref.strip():
            seeds = [
                resolved.permalink
                for resolved in await asyncio.to_thread(self._resolve_seeds, ref)
            ]
            if not seeds:
                raise NoteNotFoundError(
                    f"reference {ref!r} matched no note in this vault. Fix: check the "
                    f"permalink/title, or widen the pattern."
                )
        elif query.strip():
            candidates, degraded, reason = await self._candidates_from_query(
                query, limit=max(1, int(seed_limit))
            )
            ranked = await asyncio.to_thread(
                self._rank, candidates, max(1, int(seed_limit))
            )
            seeds = [entry.permalink for entry in ranked]
            if degraded and reason:
                warnings.append(reason)
            if not seeds:
                raise NoteNotFoundError(
                    f"query {query!r} found nothing to build context from. Fix: try "
                    f"different words, or name a starting note with ref."
                )
        else:
            raise RecallError(
                "build_context needs a starting point. Fix: pass ref (a memory:// "
                "address) or query (text that finds one)."
            )
        return await asyncio.to_thread(
            self._assemble_context,
            seeds,
            query=query,
            caller=caller,
            depth=depth,
            timeframe=timeframe,
            max_tokens=max_tokens,
            warnings=warnings,
        )

    async def resolved_body(self, permalink: str, *, model: str = "") -> ResolvedText:
        """One note's body with variants applied and value references resolved.

        This is what makes ``read`` show live values (SPEC-106 deliverable
        #5: "resolved live in recall/read output").
        """
        return await asyncio.to_thread(
            self._resolved_body_sync, permalink, parse_model_scope(model)
        )

    # ------------------------------------------------------------- candidates

    def _candidates_from_ref(self, ref: str) -> list[Candidate]:
        """Candidates from a ``memory://`` reference (possibly a glob)."""
        resolved = self._resolver.resolve(ref)
        if not resolved:
            raise NoteNotFoundError(
                f"pattern {ref!r} matched no note in this vault. Fix: widen the "
                f"pattern, or name a note directly."
            )
        return [
            Candidate(
                ref=item.ref,
                permalink=item.permalink,
                kind=item.kind,
                snippet=self._snippet_for(item),
                relevance_score=0.0,
            )
            for item in resolved
        ]

    def _resolve_seeds(self, ref: str) -> list[ResolvedRef]:
        return self._resolver.resolve(ref)

    def _snippet_for(self, resolved: ResolvedRef) -> str:
        if resolved.observation is not None:
            return f"[{resolved.observation.category}] {resolved.observation.text}"
        if resolved.relation is not None:
            return f"{resolved.relation.type} {resolved.relation.target}"
        return ""

    async def _candidates_from_query(
        self, query: str, *, limit: int
    ) -> tuple[list[Candidate], bool, str]:
        depth = max(limit * CANDIDATE_DEPTH_FACTOR, CANDIDATE_MIN_DEPTH)
        results = await self._index.search(
            query,
            mode="hybrid",
            limit=depth,
            filters=SearchFilters(exclude_types=_EXCLUDED_TYPES),
        )
        candidates = [
            Candidate(
                ref=hit.ref,
                permalink=hit.permalink,
                kind=hit.kind,
                snippet=hit.snippet,
                relevance_score=hit.score,
            )
            for hit in results.hits
        ]
        return candidates, results.degraded, results.degraded_reason

    def _rank(self, candidates: Sequence[Candidate], limit: int) -> list[RankedRef]:
        permalinks = [candidate.permalink for candidate in candidates]
        notes = self._graph.notes(permalinks)
        access = self._graph.access(permalinks)
        inbound = self._graph.inbound_counts(permalinks)
        ranked = rank_candidates(
            candidates,
            notes,
            hits={key: stat.hits for key, stat in access.items()},
            inbound=inbound,
            now=self._clock(),
            weights=self._weights,
        )
        return ranked[:limit]

    # ----------------------------------------------------------------- recall

    def _finish_recall(
        self,
        candidates: Sequence[Candidate],
        *,
        query: str,
        ref: str,
        caller: ModelScope,
        limit: int,
        include_body: bool,
        degraded: bool,
        degraded_reason: str,
    ) -> RecallResult:
        ranked = self._rank(candidates, limit)
        source = _IndexNoteSource(self._resolver, self._graph)
        entries: list[RecallEntry] = []
        warnings: list[str] = []
        for item in ranked:
            note = self._graph.note(item.permalink)
            if note is None:  # pragma: no cover - ranking already dropped these
                continue
            observations = self._served_observations(item.permalink, caller)
            body = ""
            entry_warnings: list[str] = []
            if include_body:
                resolved = self._resolve_body(note, caller, source)
                body = resolved.text
                entry_warnings = [str(warning) for warning in resolved.warnings]
                warnings.extend(entry_warnings)
            entries.append(
                RecallEntry(
                    ref=item.ref,
                    permalink=item.permalink,
                    title=item.title,
                    type=item.type,
                    kind=item.kind,
                    snippet=item.snippet,
                    score=item.score,
                    relevance_rank=item.relevance_rank,
                    recency=round(item.factors.recency, 6),
                    access=round(item.factors.access, 6),
                    significance=round(item.factors.significance, 6),
                    body=body,
                    observations=observations,
                    warnings=entry_warnings,
                )
            )
        self._record([entry.permalink for entry in entries])
        return RecallResult(
            query=query,
            ref=ref,
            model=str(caller) if caller.known else "",
            entries=entries,
            matched=len(candidates),
            degraded=degraded,
            degraded_reason=degraded_reason,
            warnings=warnings,
        )

    def _served_observations(
        self, permalink: str, caller: ModelScope
    ) -> list[RecallObservation]:
        served = resolve_variants(self._graph.observations(permalink), caller)
        return [
            RecallObservation(
                ref=obs.ref,
                category=obs.category,
                scope=obs.scope,
                text=obs.text,
                context=obs.context,
                block_id=obs.block_id,
                tags=list(obs.tags),
            )
            for obs in served
        ]

    # ---------------------------------------------------------------- context

    def _assemble_context(
        self,
        seeds: Sequence[str],
        *,
        query: str,
        caller: ModelScope,
        depth: int,
        timeframe: str,
        max_tokens: int,
        warnings: Sequence[str],
    ) -> ContextResult:
        now = self._clock()
        since = parse_timeframe(timeframe, now=now)
        result = walk(
            self._graph,
            seeds,
            depth=clamp_depth(depth),
            since=since,
            max_nodes=self._max_nodes,
        )
        notes = self._graph.notes(result.permalinks)
        ordered = self._order_nodes(result.nodes, notes, now=now)

        source = _IndexNoteSource(self._resolver, self._graph)
        header = context_header(seeds, query=query, depth=clamp_depth(depth))
        items: list[bg.BudgetItem] = []
        rendered: dict[str, _RenderedNode] = {}
        for node in ordered:
            note = notes.get(node.permalink)
            if note is None:  # pragma: no cover - walk only yields indexed notes
                continue
            render = self._render_node(node, note, caller, source)
            rendered[node.permalink] = render
            items.append(
                bg.BudgetItem(
                    key=node.permalink,
                    full=render.full,
                    summary=render.summary,
                    stub=render.stub,
                )
            )
        plan = bg.plan_budget(items, max_tokens=max_tokens, overhead=header)

        nodes: list[ContextNode] = []
        all_warnings = list(warnings)
        by_permalink = {node.permalink: node for node in ordered}
        for placement in plan.placements:
            node = by_permalink[placement.key]
            render = rendered[placement.key]
            note = notes[placement.key]
            if placement.tier == "full":
                all_warnings.extend(render.warnings)
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
                    observations=render.observations if placement.tier != "full" else [],
                    warnings=render.warnings if placement.tier == "full" else [],
                )
            )
        self._record([node.permalink for node in nodes])
        if result.truncated:
            all_warnings.append(
                f"walk stopped at {self._max_nodes} notes — narrow the depth or "
                f"the timeframe for a more focused package"
            )
        return ContextResult(
            seeds=list(seeds),
            query=query,
            model=str(caller) if caller.known else "",
            depth=clamp_depth(depth),
            timeframe=timeframe,
            max_tokens=plan.budget,
            requested_max_tokens=int(max_tokens),
            estimated_tokens=plan.tokens,
            nodes=nodes,
            dropped=list(plan.dropped),
            walk_truncated=result.truncated,
            skipped_by_timeframe=result.skipped_by_timeframe,
            degraded=plan.degraded,
            warnings=all_warnings,
        )

    def _order_nodes(
        self,
        nodes: Sequence[WalkNode],
        notes: dict[str, IndexedNote],
        *,
        now: datetime,
    ) -> list[WalkNode]:
        """Seeds first in the order given, then by depth, then by decay boost.

        Depth before score, deliberately: a direct neighbor of the seed is
        more likely to be the context the caller wants than a fresher,
        weightier note two hops away, and the budget is spent nearest-first.
        """
        access = self._graph.access([node.permalink for node in nodes])
        inbound = self._graph.inbound_counts([node.permalink for node in nodes])

        def boost(node: WalkNode) -> float:
            note = notes.get(node.permalink)
            if note is None:  # pragma: no cover - defensive
                return 0.0
            return decay_factors(
                note,
                hits=access[node.permalink].hits,
                inbound=inbound.get(node.permalink, 0),
                now=now,
                weights=self._weights,
            ).boost

        seeds = [node for node in nodes if node.is_seed]
        rest = sorted(
            (node for node in nodes if not node.is_seed),
            key=lambda node: (node.depth, -boost(node), node.permalink),
        )
        return [*seeds, *rest]

    def _render_node(
        self,
        node: WalkNode,
        note: IndexedNote,
        caller: ModelScope,
        source: NoteSource,
    ) -> _RenderedNode:
        heading = f"## {note.title} — memory://{note.permalink} [{note.type}]"
        if not node.is_seed:
            heading += f"\n> depth {node.depth} · {node.via} {node.parent}"
        resolved = self._resolve_body(note, caller, source)
        observations = self._served_observations(note.permalink, caller)
        summary_lines = self._key_observations(observations)
        summary = ""
        if summary_lines:
            summary = "\n".join([heading, "(summarized to fit the token budget)", *summary_lines])
        body = resolved.text.strip()
        return _RenderedNode(
            full=f"{heading}\n{body}\n" if body else f"{heading}\n",
            summary=f"{summary}\n" if summary else "",
            stub=f"{bg.stub_line(note.title, note.permalink)}\n",
            warnings=[str(warning) for warning in resolved.warnings],
            observations=observations,
        )

    @staticmethod
    def _key_observations(observations: Sequence[RecallObservation]) -> list[str]:
        """The observations a summary keeps: anchored ones first, then file order.

        An anchored observation is a *field* other notes embed (§5.4) — by
        construction the vault's own answer to "which fact here matters", so
        it earns its place in a shortened rendering ahead of an unanchored
        neighbor.
        """
        ordered = sorted(
            enumerate(observations), key=lambda pair: (pair[1].block_id is None, pair[0])
        )
        return [
            f"- [{obs.category}] {obs.text}"
            for _, obs in ordered[: bg.SUMMARY_OBSERVATIONS]
        ]

    # ------------------------------------------------------- shared internals

    def _resolve_body(
        self, note: IndexedNote, caller: ModelScope, source: NoteSource
    ) -> ResolvedText:
        body = self._filter_variants(note.body, caller)
        return resolve_references(
            body,
            entry=SourceNote(permalink=note.permalink, title=note.title, body=note.body),
            source=source,
            transform=lambda text: self._filter_variants(text, caller),
        )

    def _resolved_body_sync(self, permalink: str, caller: ModelScope) -> ResolvedText:
        resolved = self._resolver.resolve_one(permalink)
        note = self._graph.note(resolved.permalink)
        if note is None:
            raise NoteNotFoundError(
                f"note {permalink!r} is not in the index yet. Fix: wait for the "
                f"indexer, or run a reindex."
            )
        return self._resolve_body(note, caller, _IndexNoteSource(self._resolver, self._graph))

    def _filter_variants(self, body: str, caller: ModelScope) -> str:
        """Drop the observation lines this caller's model does not get (§5.1).

        The body is parsed with a leading newline prepended so its first line
        can never be mistaken for the opening ``---`` of frontmatter (the
        body handed in here has already had its frontmatter removed, and a
        body that legitimately *starts* with a horizontal rule must not be
        re-parsed as a header). Line numbers are therefore 1-based over
        ``"\\n" + body``, i.e. body line ``n`` is parse line ``n + 2``.
        """
        if "|" not in body:
            # No scope separator anywhere means no variant group can exist —
            # skip the parse entirely, which is the overwhelmingly common case.
            return body
        parsed = parse_note("\n" + body, "recall://variants")
        if not parsed.observations:
            return body
        dropped = dropped_indices(parsed.observations, caller)
        if not dropped:
            return body
        drop_lines = {parsed.observations[index].line - 2 for index in dropped}
        lines = body.split("\n")
        return "\n".join(
            line for index, line in enumerate(lines) if index not in drop_lines
        )

    def _record(self, permalinks: Sequence[str]) -> None:
        if not self._track_access or not permalinks:
            return
        try:
            self._graph.record_access(
                permalinks, at=self._clock().isoformat(timespec="seconds")
            )
        except Exception:  # noqa: BLE001 - a counter must never break an answer
            logger.warning("could not record access counters", exc_info=True)


class _RenderedNode:
    """A context node pre-rendered at every tier, with its warnings."""

    __slots__ = ("full", "observations", "stub", "summary", "warnings")

    def __init__(
        self,
        *,
        full: str,
        summary: str,
        stub: str,
        warnings: list[str],
        observations: list[RecallObservation],
    ) -> None:
        self.full = full
        self.summary = summary
        self.stub = stub
        self.warnings = warnings
        self.observations = observations


def context_header(seeds: Sequence[str], *, query: str, depth: int) -> str:
    """The package's one-line header — charged against the budget as overhead.

    Bounded (:func:`palaia_hub.recall.budget.elide`) so the never-zero-results
    guarantee cannot be defeated by a caller passing a very long query.
    """
    origin = bg.elide(query or ", ".join(seeds), 120)
    return f"Context for {origin!r} — depth {depth}, seeds: {len(seeds)}.\n"


def render_context(result: ContextResult) -> str:
    """The human-readable rendering of a package — what the tool returns as text.

    Deliberately assembled from the same strings the budget was computed
    over, so ``estimated_tokens`` describes exactly this text.
    """
    header = context_header(result.seeds, query=result.query, depth=result.depth)
    return header + "".join(node.text for node in result.nodes)


def recall_text(result: RecallResult) -> str:
    """The human-readable rendering of a recall answer."""
    if not result.entries:
        subject = result.ref or result.query
        return f"nothing recalled for {subject!r}"
    lines: list[str] = []
    for entry in result.entries:
        lines.append(f"## {entry.title} — memory://{entry.permalink} [{entry.type}]")
        if entry.body.strip():
            lines.append(entry.body.strip())
        elif entry.snippet:
            lines.append(entry.snippet)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


#: Vault-layer errors the gateway adapter translates into tool errors.
CALLER_ERRORS: tuple[type[Exception], ...] = (RecallError, VaultError)


__all__ = [
    "CALLER_ERRORS",
    "CANDIDATE_DEPTH_FACTOR",
    "CANDIDATE_MIN_DEPTH",
    "DEFAULT_RECALL_LIMIT",
    "DEFAULT_SEED_LIMIT",
    "RecallError",
    "RecallService",
    "context_header",
    "recall_text",
    "render_context",
]
