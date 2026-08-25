"""``VaultRefValidator`` against real vault indexes (SPEC-403 deliverable
#1's "validated to resolve in a vault the sender can read").

Two golden vaults are opened side by side, because the interesting part is
not "does this permalink exist" — the resolver already answers that — but
*whose* vault it exists in. A ref that resolves only in a vault outside the
sender's read scopes must come back unresolvable, identically to one that
exists nowhere: otherwise the refusal message becomes an oracle for "that
note is real, you just cannot see it".
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from palaia_hub.index import VaultIndex
from palaia_hub.messenger.refs import VaultRefValidator, build_vault_ref_validator
from palaia_hub.recall.refs import MemoryResolver
from palaia_hub.vault import VaultEngine

sys.path.insert(0, str(Path(__file__).parent.parent / "recall"))
from recall_helpers import open_golden  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
async def two_vaults(tmp_path: Path) -> AsyncIterator[dict[str, VaultIndex]]:
    opened: list[tuple[VaultEngine, VaultIndex]] = []
    for name in ("work", "personal"):
        opened.append(await open_golden(tmp_path / name, name))
    try:
        yield {engine.name: index for engine, index in opened}
    finally:
        for engine, index in opened:
            await index.close()
            await engine.close()


def _a_permalink(index: VaultIndex) -> str:
    """Some real permalink from this index — whichever, it just has to exist.

    Read out of the graph (``matching_glob("**")``), which is exactly what
    the resolver itself consults, so a permalink found here is one the
    validator must be able to resolve.
    """
    permalinks = index.graph.matching_glob("**")
    assert permalinks, "the golden vault fixture should contain notes"
    return sorted(permalinks)[0]


async def test_a_real_permalink_resolves(two_vaults: dict[str, VaultIndex]) -> None:
    validator = build_vault_ref_validator(two_vaults)
    permalink = _a_permalink(two_vaults["work"])

    assert validator.unresolvable([f"memory://{permalink}"]) == []


async def test_a_permalink_that_exists_nowhere_is_unresolvable(
    two_vaults: dict[str, VaultIndex],
) -> None:
    validator = build_vault_ref_validator(two_vaults)

    assert validator.unresolvable(["memory://does/not/exist"]) == [
        "memory://does/not/exist"
    ]


async def test_a_permalink_outside_the_readable_vaults_is_unresolvable(
    two_vaults: dict[str, VaultIndex],
) -> None:
    validator = build_vault_ref_validator(two_vaults)
    personal_permalink = _a_permalink(two_vaults["personal"])
    ref = f"memory://{personal_permalink}"

    # Readable: resolves. Not readable: indistinguishable from missing.
    assert validator.unresolvable([ref], readable_vaults=frozenset({"personal"})) == []
    assert validator.unresolvable([ref], readable_vaults=frozenset({"work"})) == [ref]
    assert validator.unresolvable([ref], readable_vaults=frozenset()) == [ref]


async def test_the_validator_reports_which_vaults_it_knows(
    two_vaults: dict[str, VaultIndex],
) -> None:
    validator = build_vault_ref_validator(two_vaults)
    assert validator.vault_keys == frozenset({"work", "personal"})


def test_a_validator_over_no_vaults_resolves_nothing() -> None:
    """A hub with no vaults yet: every ref is unresolvable, so a send
    carrying one is refused with the reason rather than accepted unchecked."""
    validator = VaultRefValidator({})

    assert validator.vault_keys == frozenset()
    assert validator.unresolvable(["memory://anything"]) == ["memory://anything"]


async def test_an_ambiguous_reference_counts_as_unresolvable(
    two_vaults: dict[str, VaultIndex],
) -> None:
    """An envelope's ref has to name one thing: "it matched three notes" is
    exactly as unusable to the recipient as "it matched none"."""

    class _Ambiguous:
        """A resolver stand-in that always raises the ambiguity error."""

        def resolve(self, reference: str) -> list[object]:
            from palaia_hub.vault.errors import AmbiguousReferenceError

            raise AmbiguousReferenceError(f"{reference} matches 3 notes")

    validator = VaultRefValidator(
        {"work": _Ambiguous()}  # type: ignore[dict-item] - protocol-shaped stub
    )
    assert validator.unresolvable(["memory://pricing"]) == ["memory://pricing"]

    # Sanity: the real resolver over a real index is what this stands in for.
    real = MemoryResolver(two_vaults["work"].graph, vault="work")
    assert real.resolve(f"memory://{_a_permalink(two_vaults['work'])}")
