"""SPEC-307 deliverable #2: the condition grammar."""

from __future__ import annotations

import pytest

from palaia_hub.automations.conditions import ConditionError, evaluate, validate_condition
from palaia_hub.automations.models import ConditionClause
from palaia_hub.events.schema import Envelope


def _envelope(**overrides: object) -> Envelope:
    defaults: dict[str, object] = {
        "event": "memory.entry.created",
        "data": {"severity": "high", "count": 3},
        "origin": "vault",
        "vault": "work",
    }
    defaults.update(overrides)
    return Envelope(**defaults)  # type: ignore[arg-type]


def test_empty_condition_always_matches() -> None:
    assert evaluate([], _envelope()) is True


def test_equals_on_top_level_field() -> None:
    condition = [ConditionClause(field="vault", op="equals", value="work")]
    assert evaluate(condition, _envelope()) is True
    assert evaluate(condition, _envelope(vault="personal")) is False


def test_contains_and_prefix_on_data_key() -> None:
    contains = [ConditionClause(field="data.severity", op="contains", value="igh")]
    prefix = [ConditionClause(field="data.severity", op="prefix", value="hi")]
    assert evaluate(contains, _envelope()) is True
    assert evaluate(prefix, _envelope()) is True
    assert evaluate(prefix, _envelope(data={"severity": "low"})) is False


def test_missing_data_key_never_matches() -> None:
    condition = [ConditionClause(field="data.missing", op="equals", value="x")]
    assert evaluate(condition, _envelope()) is False


def test_multiple_clauses_are_and_combined() -> None:
    condition = [
        ConditionClause(field="event", op="equals", value="memory.entry.created"),
        ConditionClause(field="data.severity", op="equals", value="low"),
    ]
    assert evaluate(condition, _envelope()) is False  # severity is "high", not "low"


def test_numeric_data_value_is_stringified_for_comparison() -> None:
    condition = [ConditionClause(field="data.count", op="equals", value="3")]
    assert evaluate(condition, _envelope()) is True


@pytest.mark.parametrize(
    "clause",
    [
        ConditionClause(field="not_a_field", op="equals", value="x"),
        ConditionClause(field="data.", op="equals", value="x"),
    ],
)
def test_unrecognized_field_is_rejected_with_a_plain_language_error(
    clause: ConditionClause,
) -> None:
    with pytest.raises(ConditionError, match="not recognized"):
        validate_condition([clause])


def test_a_valid_condition_passes_validation_without_raising() -> None:
    validate_condition(
        [
            ConditionClause(field="event", op="equals", value="memory.entry.created"),
            ConditionClause(field="data.severity", op="prefix", value="hi"),
        ]
    )
