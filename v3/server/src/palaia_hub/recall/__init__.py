"""The intelligence layer: recall, graph traversal, context assembly.

SPEC-106. Search (SPEC-104) finds notes; this package decides *which* of
them a caller gets, *how much* of each, and *in what shape*:

* :mod:`.refs` — ``memory://`` addressing: permalink, alias, title, path
  suffix, globs, block anchors, synthetic sub-note permalinks. Ambiguity is
  an error listing candidates, never a silent pick (format spec §3.2).
* :mod:`.variants` — per-model observation variants resolved as a pure
  function: exact model > provider family > scopeless base (§5.1).
* :mod:`.embeds` — value references resolved at read time, with the spec's
  ``⟦missing⟧`` / ``⟦cycle⟧`` / ``⟦depth⟧`` markers (§5.3).
* :mod:`.ranking` — decay scoring over recency, access and significance,
  layered on top of the retriever's rank rather than replacing it.
* :mod:`.traversal` — the cycle-safe, depth- and timeframe-limited relation
  walk behind ``build_context``.
* :mod:`.budget` — token budgeting that degrades notes (full → summary →
  stub) instead of cutting them mid-body.
* :mod:`.service` — :class:`RecallService`, the two public entry points the
  gateway's ``recall`` and ``build_context`` tools call.

Everything except :mod:`.service` (and :mod:`.refs`, which queries the
index) is pure: no clock, no I/O, no SQL. That is deliberate — ranking and
budgeting decisions are the ones whose regressions are silent, so they are
the ones that have to be testable as functions.
"""

from __future__ import annotations

from .budget import (
    DEFAULT_MAX_TOKENS,
    MIN_CONTEXT_TOKENS,
    BudgetItem,
    BudgetPlan,
    Placement,
    Tier,
    estimate_tokens,
    plan_budget,
)
from .embeds import (
    EMBED_CYCLE,
    EMBED_MISSING,
    MAX_EMBED_DEPTH,
    NoteSource,
    ResolutionWarning,
    ResolvedText,
    SourceNote,
    resolve_references,
)
from .models import (
    ContextNode,
    ContextResult,
    RecallEntry,
    RecallObservation,
    RecallResult,
)
from .ranking import (
    DEFAULT_TYPE_SIGNIFICANCE,
    DEFAULT_WEIGHTS,
    Candidate,
    DecayFactors,
    RankedRef,
    RankingWeights,
    decay_factors,
    rank_candidates,
    weights_from_settings,
)
from .refs import MemoryRef, MemoryResolver, ResolvedRef, parse_memory_ref
from .service import (
    DEFAULT_RECALL_LIMIT,
    RecallError,
    RecallService,
    recall_text,
    render_context,
)
from .traversal import (
    DEFAULT_DEPTH,
    MAX_DEPTH,
    WalkNode,
    WalkResult,
    parse_timeframe,
    walk,
)
from .variants import (
    ModelScope,
    parse_model_scope,
    resolve_variants,
)

__all__ = [
    "DEFAULT_DEPTH",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_RECALL_LIMIT",
    "DEFAULT_TYPE_SIGNIFICANCE",
    "DEFAULT_WEIGHTS",
    "EMBED_CYCLE",
    "EMBED_MISSING",
    "MAX_DEPTH",
    "MAX_EMBED_DEPTH",
    "MIN_CONTEXT_TOKENS",
    "BudgetItem",
    "BudgetPlan",
    "Candidate",
    "ContextNode",
    "ContextResult",
    "DecayFactors",
    "MemoryRef",
    "MemoryResolver",
    "ModelScope",
    "NoteSource",
    "Placement",
    "RankedRef",
    "RankingWeights",
    "RecallEntry",
    "RecallError",
    "RecallObservation",
    "RecallResult",
    "RecallService",
    "ResolutionWarning",
    "ResolvedRef",
    "ResolvedText",
    "SourceNote",
    "Tier",
    "WalkNode",
    "WalkResult",
    "decay_factors",
    "estimate_tokens",
    "parse_memory_ref",
    "parse_model_scope",
    "parse_timeframe",
    "plan_budget",
    "rank_candidates",
    "recall_text",
    "render_context",
    "resolve_references",
    "resolve_variants",
    "walk",
    "weights_from_settings",
]
