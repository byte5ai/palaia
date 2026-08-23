"""Token budgeting — fitting a context package into ``max_tokens``.

The rule SPEC-106 sets is narrow and load-bearing: **never truncate a note
mid-body**. A context package that ends a note halfway through hands the
model half a sentence and full confidence; that is worse than not sending
the note at all. So a note that does not fit is *degraded*, not cut:

1. **full** — the note's body, embeds resolved, variants applied.
2. **summary** — its title plus its key observations. Observations are
   already atomic, self-contained facts (format spec §5.1), which is exactly
   what makes them the right summary unit: dropping one loses a fact but
   never leaves a mutilated one. A note with no observations has no summary
   tier — there is nothing to shorten it *to* without cutting prose.
3. **stub** — one line naming the note, so the model at least learns the
   note exists and can ask for it by permalink.

**Never zero results.** The first item is always placed, at the smallest
tier if need be, and the stub is bounded (:data:`STUB_MAX_CHARS`) so it fits
inside :data:`MIN_CONTEXT_TOKENS`. That is also why ``max_tokens`` is raised
to that floor: a budget too small to name a single note is not a budget, it
is a refusal, and the package reports the effective figure it actually used.

**The estimator is the contract.** No tokenizer is bundled (that would tie
the hub to one model family's vocabulary and change the answer when the
caller changes model), so tokens are estimated from characters at
:data:`CHARS_PER_TOKEN`. The bound the property test asserts is over *this*
estimate, applied to the *rendered text that is actually returned* — so the
number in the package and the text in the package can never disagree.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

#: Characters per token. Slightly below the ~4 rule of thumb for English
#: prose, so the estimate errs toward over-counting: filling less of the
#: budget than allowed is a smaller failure than blowing through it.
CHARS_PER_TOKEN = 3.5

#: Budget floor. Below this a package could not even name one note, so
#: ``max_tokens`` is raised to it (and the package says so).
MIN_CONTEXT_TOKENS = 128

#: Default ``max_tokens`` for ``build_context``: a few thousand tokens is a
#: context package, not a context dump — enough for a seed note plus its
#: immediate graph, which is what "continue where we left off" needs.
DEFAULT_MAX_TOKENS = 4000

#: Hard ceiling on a stub line, so the never-zero-results guarantee cannot be
#: defeated by a note with a 4 KB title.
STUB_MAX_CHARS = 200

#: Observations kept in a summary. Three is what fits in a couple of lines
#: and is enough to tell whether the full note is worth asking for.
SUMMARY_OBSERVATIONS = 3

#: How the three tiers are named in the package.
Tier = Literal["full", "summary", "stub"]

_TIER_ORDER: tuple[Tier, ...] = ("full", "summary", "stub")

_ELLIPSIS = "…"


def estimate_tokens(text: str) -> int:
    """Estimated tokens in ``text`` (see the module docstring's last note)."""
    if not text:
        return 0
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def elide(text: str, limit: int) -> str:
    """``text`` shortened to ``limit`` characters, ellipsis included."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    if limit <= 1:
        return _ELLIPSIS[:limit]
    return flat[: limit - 1].rstrip() + _ELLIPSIS


def stub_line(title: str, permalink: str) -> str:
    """One bounded line naming a note: ``- Title (permalink)``."""
    line = f"- {title} ({permalink})"
    return elide(line, STUB_MAX_CHARS)


@dataclass(frozen=True, slots=True)
class BudgetItem:
    """One candidate for the package, pre-rendered at every available tier.

    ``summary`` may be empty — that means this item has no summary tier and
    degrades straight from full to stub (a note with no observations).
    """

    key: str
    full: str
    summary: str
    stub: str

    def text_for(self, tier: Tier) -> str:
        if tier == "full":
            return self.full
        if tier == "summary":
            return self.summary
        return self.stub

    def tiers(self) -> tuple[Tier, ...]:
        """The tiers this item can actually be rendered at, widest first."""
        return tuple(tier for tier in _TIER_ORDER if self.text_for(tier))


@dataclass(frozen=True, slots=True)
class Placement:
    """One item as it made it into the package."""

    key: str
    tier: Tier
    text: str
    tokens: int


@dataclass(frozen=True, slots=True)
class BudgetPlan:
    """The outcome of fitting items into a budget."""

    placements: tuple[Placement, ...]
    dropped: tuple[str, ...]
    tokens: int
    budget: int
    """The *effective* budget — ``max_tokens`` raised to the floor if needed."""

    @property
    def degraded(self) -> bool:
        """True when anything had to be summarized, stubbed or dropped."""
        return bool(self.dropped) or any(p.tier != "full" for p in self.placements)


def effective_budget(max_tokens: int) -> int:
    """``max_tokens``, never below :data:`MIN_CONTEXT_TOKENS`."""
    return max(int(max_tokens), MIN_CONTEXT_TOKENS)


def plan_budget(
    items: Sequence[BudgetItem], *, max_tokens: int, overhead: str = ""
) -> BudgetPlan:
    """Fit ``items`` into ``max_tokens``, degrading tier by tier.

    ``items`` must arrive in priority order — the earlier an item, the more
    of the budget it may claim. ``overhead`` is text the caller will emit
    alongside the placements (a package header); its cost is charged against
    the budget so the total the caller returns stays inside it.
    """
    budget = effective_budget(max_tokens)
    used = estimate_tokens(overhead)
    placements: list[Placement] = []
    dropped: list[str] = []
    for item in items:
        placed = False
        for tier in item.tiers():
            text = item.text_for(tier)
            cost = estimate_tokens(text)
            if used + cost <= budget:
                placements.append(Placement(key=item.key, tier=tier, text=text, tokens=cost))
                used += cost
                placed = True
                break
        if placed:
            continue
        if not placements:
            # Never zero results: the first item goes in as a stub even if
            # the caller's budget was unreasonably small. `stub_line` is
            # bounded and the budget has a floor, so this cannot overshoot —
            # `tests/recall/test_budget.py` pins that arithmetic.
            stub = item.stub or stub_line(item.key, item.key)
            cost = estimate_tokens(stub)
            placements.append(Placement(key=item.key, tier="stub", text=stub, tokens=cost))
            used += cost
            continue
        dropped.append(item.key)
    return BudgetPlan(
        placements=tuple(placements),
        dropped=tuple(dropped),
        tokens=used,
        budget=budget,
    )


__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_MAX_TOKENS",
    "MIN_CONTEXT_TOKENS",
    "STUB_MAX_CHARS",
    "SUMMARY_OBSERVATIONS",
    "BudgetItem",
    "BudgetPlan",
    "Placement",
    "Tier",
    "effective_budget",
    "elide",
    "estimate_tokens",
    "plan_budget",
    "stub_line",
]
