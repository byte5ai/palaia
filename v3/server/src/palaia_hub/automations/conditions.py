"""The condition grammar (SPEC-307 deliverable #2).

A fixed, closed vocabulary — **not a general expression language** (fixed
decision, see ``docs/events.md`` §automations): a field name (``event``,
``origin``, ``vault``, or a ``data.<key>`` path), one of three operators
(``equals``/``contains``/``prefix``), and a plain string value. A condition
is a list of clauses, AND-combined; an empty list always matches. Every
clause is checked against the envelope as a string comparison — there is no
numeric/boolean coercion, no regex, no nesting, and nothing here ever calls
``eval``.
"""

from __future__ import annotations

from typing import Any

from ..events.schema import Envelope
from .models import ConditionClause

_TOP_LEVEL_FIELDS = {"event", "origin", "vault"}
_VALID_OPS = {"equals", "contains", "prefix"}


class ConditionError(ValueError):
    """A malformed condition — always carries a plain-language message
    naming exactly what is wrong (acceptance: "malformed condition rejected
    with a plain-language error")."""


def validate_condition(condition: list[ConditionClause]) -> None:
    """Raise :class:`ConditionError` if any clause is not well-formed."""
    for clause in condition:
        if clause.op not in _VALID_OPS:
            raise ConditionError(
                f"condition field {clause.field!r} uses operator {clause.op!r}, "
                f"which is not one of equals/contains/prefix."
            )
        if clause.field in _TOP_LEVEL_FIELDS:
            continue
        if clause.field.startswith("data.") and len(clause.field) > len("data."):
            continue
        raise ConditionError(
            f"condition field {clause.field!r} is not recognized. Use one of "
            f"'event', 'origin', 'vault', or 'data.<key>' (e.g. 'data.severity')."
        )


def _field_value(field: str, envelope: Envelope) -> str | None:
    """The envelope's value for ``field`` as a string, or ``None`` if the
    field (a ``data.<key>`` path) is not present."""
    if field == "event":
        return envelope.event
    if field == "origin":
        return envelope.origin
    if field == "vault":
        return envelope.vault
    key = field[len("data.") :]
    if key not in envelope.data:
        return None
    return _stringify(envelope.data[key])


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _clause_matches(clause: ConditionClause, envelope: Envelope) -> bool:
    actual = _field_value(clause.field, envelope)
    if actual is None:
        return False
    if clause.op == "equals":
        return actual == clause.value
    if clause.op == "contains":
        return clause.value in actual
    if clause.op == "prefix":
        return actual.startswith(clause.value)
    raise ConditionError(f"unknown operator {clause.op!r}")  # pragma: no cover - validated earlier


def evaluate(condition: list[ConditionClause], envelope: Envelope) -> bool:
    """``True`` iff every clause matches ``envelope`` (AND-combined; an
    empty condition always matches)."""
    return all(_clause_matches(clause, envelope) for clause in condition)


__all__ = ["ConditionError", "evaluate", "validate_condition"]
