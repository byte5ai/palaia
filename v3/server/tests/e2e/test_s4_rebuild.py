"""S4 "delete index -> reindex -> query battery identical" (SPEC-113).

Format spec §10: "the index is disposable: reindex MUST reproduce identical
query results from files alone". This SPEC's search adapter has no
persistent index of its own yet (SPEC-104 is not merged) — its "index" is
the engine's in-memory identity catalog plus a linear scan, so this
scenario's rebuild step is ``engine.close()`` (drops the catalog) followed
by a fresh ``engine.open()`` (rebuilds it from files, and runs
:meth:`~palaia_hub.vault.VaultDoctor.reindex` too, so the doctor's own
rebuild hook is exercised, not only the catalog refresh). The assertion
that matters is untouched by which index implementation is behind it: the
same query battery, run through the same :class:`EngineVaultService`
adapter the gateway uses, must return byte-for-byte identical permalink
sets before and after.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from query_battery import CANONICAL_QUERIES

from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultDoctor, VaultEngine

pytestmark = pytest.mark.anyio


class _RecordingSink:
    """Minimal :class:`~palaia_hub.vault.ReindexSink` — just counts notes."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def begin(self, vault: str) -> None:
        self.paths = []

    def emit(self, note: object) -> None:  # noqa: ANN001 - matches ReindexSink.emit(Note)
        self.paths.append(getattr(note, "path", ""))

    def finish(self) -> None:
        pass


async def test_reindex_reproduces_identical_query_results(golden_work_vault: Path) -> None:
    engine = VaultEngine(golden_work_vault, "work")
    await engine.open()
    service = EngineVaultService(engine)

    before: dict[str, set[str]] = {}
    for query in CANONICAL_QUERIES:
        hits = await service.search(query, limit=100)
        before[query] = {hit.permalink for hit in hits}
    note_count_before = len(engine.catalog)

    # Simulate "delete the index": drop the in-memory catalog and the
    # doctor's own rebuild hook, then rebuild everything from files alone.
    await engine.close()
    engine = VaultEngine(golden_work_vault, "work")
    await engine.open()
    reindexed = await engine.reindex(_RecordingSink())
    assert reindexed == note_count_before

    rebuilt_service = EngineVaultService(engine)
    after: dict[str, set[str]] = {}
    for query in CANONICAL_QUERIES:
        hits = await rebuilt_service.search(query, limit=100)
        after[query] = {hit.permalink for hit in hits}

    assert after == before

    findings = await VaultDoctor(engine).verify()
    fatal = [f for f in findings if f.severity == "error"]
    assert fatal == [], fatal

    await engine.close()
