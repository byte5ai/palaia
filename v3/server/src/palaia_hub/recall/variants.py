"""Per-model observation variants — resolution as a pure function.

Format spec §5.1: consecutive observation lines sharing a ``category`` where
at least one carries a ``| scope`` form a **variant group**, and exactly one
line of that group is served to a given caller. Specificity order:

1. ``provider/model`` — an exact match on the calling model
2. ``provider`` — the model's provider family
3. scopeless (or the explicit ``default`` scope) — the base line

A caller whose model matches nothing in a group gets that group's base line;
a group with no base line serves such a caller **nothing** (the parser
already warned ``variant-no-base`` for it). Everything else in the note is
untouched: a run of same-category observations where *no* line is scoped is
not a variant group at all — those are independent facts that happen to
share a category, and dropping all but one of them would be data loss.

Nothing in this module does I/O, reads a clock, or touches the index: it is
a total function from (observation lines, caller identity) to the subset
served, which is what makes the table-driven tests in
``tests/recall/test_variants.py`` the whole contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

#: The scope spelling that means "this is the base line", stated explicitly
#: rather than by omission (§5.1's ``scope = ... | "default"``).
DEFAULT_SCOPE = "default"


@dataclass(frozen=True, slots=True)
class ModelScope:
    """The calling model's identity, normalized to ``provider`` + ``model``.

    An empty :attr:`provider` means "the caller did not say" — such a caller
    matches only base lines, which is exactly the unknown-model behavior the
    spec asks for.
    """

    provider: str = ""
    model: str = ""

    @property
    def qualified(self) -> str:
        """``provider/model`` when both are known, else ``""``."""
        return f"{self.provider}/{self.model}" if self.provider and self.model else ""

    @property
    def known(self) -> bool:
        return bool(self.provider)

    def __str__(self) -> str:
        return self.qualified or self.provider or "(unknown)"


def parse_model_scope(raw: str | None) -> ModelScope:
    """Parse a caller-supplied model identity into a :class:`ModelScope`.

    Accepts what clients actually send: ``"anthropic/opus-5"``,
    ``"anthropic"``, ``"Anthropic/Opus-5"``, a leading/trailing slash, or
    nothing at all. Anything else — including a bare model name with no
    provider — is treated as unknown rather than guessed at: mapping
    ``"opus-5"`` to a provider would need a hardcoded model registry, and a
    stale registry silently serving the wrong variant is worse than serving
    the base line.
    """
    text = (raw or "").strip().strip("/").casefold()
    if not text:
        return ModelScope()
    provider, _, model = text.partition("/")
    provider = provider.strip()
    model = model.strip()
    if not provider:
        return ModelScope()
    return ModelScope(provider=provider, model=model)


class VariantLine(Protocol):
    """The two fields variant resolution reads off an observation."""

    @property
    def category(self) -> str: ...

    @property
    def scope(self) -> str | None: ...


def _normalized_scope(line: VariantLine) -> str:
    """The line's scope, casefolded; ``""`` for a base line."""
    scope = (line.scope or "").strip().casefold()
    return "" if scope == DEFAULT_SCOPE else scope


def variant_groups[LineT: VariantLine](lines: Sequence[LineT]) -> list[list[int]]:
    """Group indices into maximal runs of consecutive same-category lines.

    Returned in file order, one list per run — including runs of length one
    and runs that are not variant groups. Callers decide what to do with a
    run; :func:`resolve_variants` only collapses the ones that carry a scope.
    """
    groups: list[list[int]] = []
    for index, line in enumerate(lines):
        key = line.category.strip().casefold()
        if groups and lines[groups[-1][-1]].category.strip().casefold() == key:
            groups[-1].append(index)
            continue
        groups.append([index])
    return groups


def select_variant[LineT: VariantLine](
    lines: Sequence[LineT], group: Sequence[int], caller: ModelScope
) -> int | None:
    """Index of the one line of ``group`` served to ``caller``, or ``None``.

    ``None`` means this group has nothing for this caller — only possible
    for a scoped-only group (``variant-no-base``).
    """
    tiers: list[str] = []
    if caller.qualified:
        tiers.append(caller.qualified)
    if caller.provider:
        tiers.append(caller.provider)
    for wanted in tiers:
        for index in group:
            if _normalized_scope(lines[index]) == wanted:
                return index
    for index in group:
        if not _normalized_scope(lines[index]):
            return index
    return None


def resolve_variants[LineT: VariantLine](
    lines: Sequence[LineT], caller: ModelScope
) -> tuple[LineT, ...]:
    """The observation lines served to ``caller``, in file order.

    Non-variant runs pass through whole; every variant group contributes at
    most one line.
    """
    return tuple(lines[index] for index in resolved_indices(lines, caller))


def resolved_indices[LineT: VariantLine](
    lines: Sequence[LineT], caller: ModelScope
) -> tuple[int, ...]:
    """Indices of the lines :func:`resolve_variants` keeps, in file order."""
    kept: list[int] = []
    for group in variant_groups(lines):
        if not any(_normalized_scope(lines[index]) for index in group):
            kept.extend(group)
            continue
        chosen = select_variant(lines, group, caller)
        if chosen is not None:
            kept.append(chosen)
    return tuple(kept)


def dropped_indices[LineT: VariantLine](
    lines: Sequence[LineT], caller: ModelScope
) -> frozenset[int]:
    """Indices of the lines variant resolution withholds from ``caller``."""
    kept = set(resolved_indices(lines, caller))
    return frozenset(index for index in range(len(lines)) if index not in kept)


__all__ = [
    "DEFAULT_SCOPE",
    "ModelScope",
    "VariantLine",
    "dropped_indices",
    "parse_model_scope",
    "resolve_variants",
    "resolved_indices",
    "select_variant",
    "variant_groups",
]
