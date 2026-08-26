"""Token budgeting — including SPEC-106's budget property test.

The acceptance criterion has two halves that pull against each other:
*"assembled context ≤ max_tokens for random vaults, while never returning
zero results when matches exist"*. A budget of 1 token cannot both hold a
note's name and stay under 1 token, so the contract resolves it explicitly:
``max_tokens`` is raised to :data:`MIN_CONTEXT_TOKENS`, the package reports
the figure it actually used, and the bound is asserted against *that*.

:func:`test_min_budget_always_fits_a_stub` is what makes that resolution
sound rather than convenient — it pins the arithmetic that guarantees the
smallest possible rendering fits inside the floor.
"""

from __future__ import annotations

import random

import pytest

from palaia_hub.recall.budget import (
    CHARS_PER_TOKEN,
    MIN_CONTEXT_TOKENS,
    STUB_MAX_CHARS,
    BudgetItem,
    effective_budget,
    elide,
    estimate_tokens,
    plan_budget,
    stub_line,
)


def item(key: str, *, full: str, summary: str = "", stub: str = "") -> BudgetItem:
    return BudgetItem(key=key, full=full, summary=summary, stub=stub or stub_line(key, key))


# --------------------------------------------------------------------------
# The estimator and the elider
# --------------------------------------------------------------------------

def test_estimate_is_monotone_in_length() -> None:
    previous = 0
    for length in range(0, 500, 17):
        current = estimate_tokens("x" * length)
        assert current >= previous
        previous = current


def test_estimate_of_empty_text_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_matches_the_documented_ratio() -> None:
    text = "x" * 350
    assert estimate_tokens(text) == pytest.approx(350 / CHARS_PER_TOKEN, abs=1)


def test_elide_never_exceeds_its_limit() -> None:
    for limit in range(0, 40):
        assert len(elide("a very long title that keeps going and going", limit)) <= limit


def test_elide_collapses_whitespace_so_a_stub_stays_one_line() -> None:
    assert "\n" not in elide("multi\nline\ttitle", 100)


def test_stub_line_is_bounded() -> None:
    huge = "T" * 5000
    assert len(stub_line(huge, huge)) <= STUB_MAX_CHARS


# --------------------------------------------------------------------------
# The floor: what makes "never zero results" compatible with the bound
# --------------------------------------------------------------------------

def test_min_budget_always_fits_a_stub() -> None:
    """A stub, plus a bounded header, must fit inside the budget floor.

    If this ever fails, the never-zero-results guarantee and the
    ``<= max_tokens`` bound have become mutually exclusive — raise
    MIN_CONTEXT_TOKENS or tighten STUB_MAX_CHARS, do not weaken either
    promise.
    """
    worst_stub = estimate_tokens("x" * STUB_MAX_CHARS)
    # The header is bounded by its own elision to 120 chars plus ~60 of
    # fixed framing (see recall.service.context_header).
    worst_header = estimate_tokens("x" * 180)
    assert worst_stub + worst_header <= MIN_CONTEXT_TOKENS


def test_effective_budget_raises_absurd_values_to_the_floor() -> None:
    assert effective_budget(0) == MIN_CONTEXT_TOKENS
    assert effective_budget(-100) == MIN_CONTEXT_TOKENS
    assert effective_budget(MIN_CONTEXT_TOKENS + 1) == MIN_CONTEXT_TOKENS + 1


# --------------------------------------------------------------------------
# Tier degradation
# --------------------------------------------------------------------------

def test_everything_fits_at_full_tier_when_the_budget_is_generous() -> None:
    plan = plan_budget([item("a", full="A" * 40), item("b", full="B" * 40)], max_tokens=4000)
    assert [placement.tier for placement in plan.placements] == ["full", "full"]
    assert plan.dropped == ()
    assert not plan.degraded


def test_a_note_that_does_not_fit_is_summarized_not_cut() -> None:
    full = "F" * 4000
    summary = "- [rate] 100/min"
    plan = plan_budget([item("a", full=full, summary=summary)], max_tokens=200)
    assert [placement.tier for placement in plan.placements] == ["summary"]
    assert plan.placements[0].text == summary
    # The whole point: no prefix of `full` appears anywhere.
    assert full[:100] not in plan.placements[0].text
    assert plan.degraded


def test_a_note_with_no_observations_degrades_straight_to_a_stub() -> None:
    plan = plan_budget([item("a", full="F" * 4000, summary="")], max_tokens=200)
    assert [placement.tier for placement in plan.placements] == ["stub"]


def test_a_tight_budget_stubs_everything_before_it_drops_anything() -> None:
    # Stubs are cheap by construction, so ten oversized notes all still get
    # *named* inside the floor. That is the intended behavior: the caller
    # learns what exists and can ask for any of it by permalink.
    items = [item(str(n), full="F" * 600) for n in range(10)]
    plan = plan_budget(items, max_tokens=MIN_CONTEXT_TOKENS)
    assert plan.tokens <= plan.budget
    assert [placement.tier for placement in plan.placements] == ["stub"] * 10
    assert plan.dropped == ()


def test_items_are_dropped_only_once_not_even_a_stub_fits() -> None:
    items = [item(str(n), full="F" * 600, stub="s" * STUB_MAX_CHARS) for n in range(20)]
    plan = plan_budget(items, max_tokens=MIN_CONTEXT_TOKENS)
    assert plan.tokens <= plan.budget
    assert plan.placements, "the first item must always be placed"
    assert plan.dropped, "with twenty maximal stubs, some must be dropped"


def test_priority_order_is_respected() -> None:
    items = [item("first", full="F" * 300), item("second", full="S" * 300)]
    plan = plan_budget(items, max_tokens=MIN_CONTEXT_TOKENS)
    assert plan.placements[0].key == "first"


def test_overhead_is_charged_against_the_budget() -> None:
    body = "F" * 300
    without = plan_budget([item("a", full=body)], max_tokens=200)
    with_header = plan_budget([item("a", full=body)], max_tokens=200, overhead="H" * 500)
    assert with_header.tokens > without.tokens
    assert with_header.tokens <= with_header.budget


# --------------------------------------------------------------------------
# The property test
# --------------------------------------------------------------------------

def _random_items(rng: random.Random) -> list[BudgetItem]:
    items: list[BudgetItem] = []
    for index in range(rng.randint(1, 25)):
        key = f"notes/random-{index}"
        body_len = rng.choice([0, 1, 40, 400, 4000, 40_000])
        observations = rng.randint(0, 4)
        summary = (
            "\n".join(f"- [cat{n}] {'o' * rng.randint(1, 120)}" for n in range(observations))
            if observations
            else ""
        )
        items.append(
            BudgetItem(
                key=key,
                full="b" * body_len,
                summary=summary,
                stub=stub_line("T" * rng.randint(1, 300), key),
            )
        )
    return items


@pytest.mark.parametrize("seed", range(60))
def test_property_plan_never_exceeds_the_budget_and_never_returns_nothing(seed: int) -> None:
    rng = random.Random(seed)
    items = _random_items(rng)
    requested = rng.choice([0, 1, 7, 64, MIN_CONTEXT_TOKENS, 300, 1000, 4000, 100_000])
    overhead = "H" * rng.randint(0, 180)
    plan = plan_budget(items, max_tokens=requested, overhead=overhead)

    assert plan.tokens <= plan.budget, (
        f"seed={seed}: plan used {plan.tokens} of a {plan.budget}-token budget"
    )
    assert plan.placements, f"seed={seed}: items existed but nothing was placed"
    # The reported cost is the cost of the text actually returned.
    rendered = overhead + "".join(placement.text for placement in plan.placements)
    assert estimate_tokens(rendered) <= plan.budget
    # Placements and drops together account for every item, exactly once.
    accounted = [placement.key for placement in plan.placements] + list(plan.dropped)
    assert sorted(accounted) == sorted(item.key for item in items)
