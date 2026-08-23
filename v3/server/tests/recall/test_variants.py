"""Per-model variant resolution — the table-driven contract (SPEC-106 #4).

The acceptance criterion is stated as a table ("exact model > family >
default; unknown model → default; no variant → base observation"), so the
tests are a table: one row per (group, caller) pair with the exact expected
outcome. Anything the resolver does that this table does not describe is,
by construction, not part of the contract.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from palaia_hub.recall.variants import (
    ModelScope,
    dropped_indices,
    parse_model_scope,
    resolve_variants,
    select_variant,
    variant_groups,
)
from palaia_hub.vault.parse import parse_note


@dataclass(frozen=True, slots=True)
class Line:
    """A stand-in observation: exactly the two fields resolution reads."""

    category: str
    scope: str | None
    text: str = ""


# --------------------------------------------------------------------------
# parse_model_scope
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("anthropic/opus-5", ModelScope("anthropic", "opus-5")),
        ("Anthropic/Opus-5", ModelScope("anthropic", "opus-5")),
        ("  anthropic/opus-5  ", ModelScope("anthropic", "opus-5")),
        ("/anthropic/opus-5/", ModelScope("anthropic", "opus-5")),
        ("anthropic", ModelScope("anthropic", "")),
        ("openai/gpt-5.2", ModelScope("openai", "gpt-5.2")),
        ("", ModelScope()),
        ("   ", ModelScope()),
        (None, ModelScope()),
        # A bare model name with no provider is *not* guessed at (see the
        # function's docstring: a stale model registry serving the wrong
        # variant is worse than serving the base line).
        ("/opus-5", ModelScope("opus-5", "")),
    ],
)
def test_parse_model_scope_table(raw: str | None, expected: ModelScope) -> None:
    assert parse_model_scope(raw) == expected


def test_unknown_scope_stringifies_readably() -> None:
    assert str(ModelScope()) == "(unknown)"
    assert str(ModelScope("anthropic")) == "anthropic"
    assert str(ModelScope("anthropic", "opus-5")) == "anthropic/opus-5"


# --------------------------------------------------------------------------
# The specificity table
# --------------------------------------------------------------------------

#: The §5.1 example group, verbatim from the format spec.
SPEC_GROUP = (
    Line("how-to-apply", None, "Prefer the compact form of this rule."),
    Line("how-to-apply", "anthropic/opus-5", "Use the extended form with rationale."),
    Line("how-to-apply", "openai", "Use imperative phrasing."),
)

#: A group with only scoped lines — `variant-no-base` at parse time.
NO_BASE_GROUP = (
    Line("tone", "anthropic", "Warm."),
    Line("tone", "openai", "Terse."),
)

#: Same category, no scope anywhere: not a variant group at all.
PLAIN_GROUP = (
    Line("gotcha", None, "First gotcha."),
    Line("gotcha", None, "Second gotcha."),
)

#: `default` is the explicit spelling of "this is the base line" (§5.1).
EXPLICIT_DEFAULT_GROUP = (
    Line("style", "default", "Base style."),
    Line("style", "anthropic", "Anthropic style."),
)


@pytest.mark.parametrize(
    ("lines", "caller", "expected"),
    [
        # exact model wins over provider and over base
        (SPEC_GROUP, "anthropic/opus-5", ["Use the extended form with rationale."]),
        # provider family wins over base
        (SPEC_GROUP, "openai", ["Use imperative phrasing."]),
        (SPEC_GROUP, "openai/gpt-5.2", ["Use imperative phrasing."]),
        # a provider with an exact-scope sibling but no own exact match falls
        # back to *its* provider tier, not to another provider's exact line
        (SPEC_GROUP, "anthropic", ["Prefer the compact form of this rule."]),
        # unknown model -> base
        (SPEC_GROUP, "google/gemini-3", ["Prefer the compact form of this rule."]),
        (SPEC_GROUP, "", ["Prefer the compact form of this rule."]),
        # scoped-only group: matching callers get their line...
        (NO_BASE_GROUP, "anthropic/opus-5", ["Warm."]),
        (NO_BASE_GROUP, "openai", ["Terse."]),
        # ...and a non-matching caller gets nothing at all
        (NO_BASE_GROUP, "google/gemini-3", []),
        (NO_BASE_GROUP, "", []),
        # no scope anywhere: every line survives, for everyone
        (PLAIN_GROUP, "anthropic/opus-5", ["First gotcha.", "Second gotcha."]),
        (PLAIN_GROUP, "", ["First gotcha.", "Second gotcha."]),
        # `default` behaves exactly like a scopeless base line
        (EXPLICIT_DEFAULT_GROUP, "anthropic", ["Anthropic style."]),
        (EXPLICIT_DEFAULT_GROUP, "google", ["Base style."]),
        (EXPLICIT_DEFAULT_GROUP, "", ["Base style."]),
    ],
)
def test_variant_resolution_table(
    lines: tuple[Line, ...], caller: str, expected: list[str]
) -> None:
    served = resolve_variants(lines, parse_model_scope(caller))
    assert [line.text for line in served] == expected


def test_exactly_one_line_per_variant_group() -> None:
    for caller in ("anthropic/opus-5", "openai", "google/gemini-3", ""):
        served = resolve_variants(SPEC_GROUP, parse_model_scope(caller))
        assert len(served) == 1, f"{caller!r} got {len(served)} lines from one group"


def test_dropped_indices_are_the_complement_of_the_served_ones() -> None:
    caller = parse_model_scope("openai")
    dropped = dropped_indices(SPEC_GROUP, caller)
    assert dropped == frozenset({0, 1})
    assert select_variant(SPEC_GROUP, [0, 1, 2], caller) == 2


# --------------------------------------------------------------------------
# Grouping: "consecutive" is load-bearing
# --------------------------------------------------------------------------

def test_only_consecutive_same_category_lines_form_a_group() -> None:
    lines = (
        Line("rule", None, "base A"),
        Line("rule", "openai", "openai A"),
        Line("note", None, "interruption"),
        Line("rule", None, "base B"),
        Line("rule", "openai", "openai B"),
    )
    assert variant_groups(lines) == [[0, 1], [2], [3, 4]]
    served = resolve_variants(lines, parse_model_scope("openai"))
    # Two separate groups, so two variant lines survive — not one.
    assert [line.text for line in served] == ["openai A", "interruption", "openai B"]


def test_a_group_split_by_another_category_is_not_collapsed_across_it() -> None:
    lines = (
        Line("rule", "openai", "openai only"),
        Line("other", None, "unrelated"),
        Line("rule", None, "base"),
    )
    served = resolve_variants(lines, parse_model_scope("google"))
    # First group is scoped-only and does not match google -> nothing.
    # Third line is its own group with a base -> served.
    assert [line.text for line in served] == ["unrelated", "base"]


def test_first_base_line_wins_when_a_group_has_several() -> None:
    lines = (
        Line("rule", None, "first base"),
        Line("rule", None, "second base"),
        Line("rule", "openai", "openai"),
    )
    served = resolve_variants(lines, parse_model_scope("google"))
    assert [line.text for line in served] == ["first base"]


def test_resolution_is_stable_across_repeated_calls() -> None:
    caller = parse_model_scope("anthropic/opus-5")
    first = resolve_variants(SPEC_GROUP, caller)
    for _ in range(5):
        assert resolve_variants(SPEC_GROUP, caller) == first


# --------------------------------------------------------------------------
# Against the real parser, on the format spec's own example
# --------------------------------------------------------------------------

SPEC_EXAMPLE = """---
title: Response Length
permalink: rules/response-length
---

- [how-to-apply] Prefer the compact form of this rule.
- [how-to-apply | anthropic/opus-5] Use the extended form with rationale.
- [how-to-apply | openai] Use imperative phrasing.
"""


@pytest.mark.parametrize(
    ("caller", "expected"),
    [
        ("anthropic/opus-5", "Use the extended form with rationale."),
        ("openai", "Use imperative phrasing."),
        ("openai/gpt-5.2", "Use imperative phrasing."),
        ("google/gemini-3", "Prefer the compact form of this rule."),
        ("", "Prefer the compact form of this rule."),
    ],
)
def test_resolution_over_real_parser_output(caller: str, expected: str) -> None:
    parsed = parse_note(SPEC_EXAMPLE, "rules/response-length.md")
    served = resolve_variants(parsed.observations, parse_model_scope(caller))
    assert [obs.text for obs in served] == [expected]
