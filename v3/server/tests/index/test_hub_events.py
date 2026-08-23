"""SPEC-201's ``index.reindexed``/``index.embed_backlog_drained``/
``doctor.finding`` hook point on :class:`~palaia_hub.index.VaultIndex`.

Unit-level: the real wiring of this hook onto the hub's public event bus
happens wherever a running hub constructs a ``VaultIndex`` — no production
call path does that yet (see this SPEC's PR notes) — so what is tested
here is the contract the hook must honor once that wiring lands: every
call carries the vault's name, and the backlog-drained signal fires only
once the backlog actually reaches zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.vault import EventBus, Finding, VaultEngine


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _open_index(
    tmp_path: Path, *, on_event: object
) -> tuple[VaultEngine, VaultIndex]:
    engine = VaultEngine(tmp_path / "vault", "work", bus=EventBus())
    await engine.open(purpose="hub events test", create=True)
    index = VaultIndex(
        engine,
        embedding=EmbeddingConfig(enabled=False),
        on_event=on_event,  # type: ignore[arg-type]
    )
    await index.open(build=True, start_worker=False)
    return engine, index


@pytest.mark.anyio
async def test_reindex_emits_index_reindexed_with_the_vault_name(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    engine, index = await _open_index(
        tmp_path, on_event=lambda name, data: calls.append((name, data))
    )
    try:
        calls.clear()  # drop the open()-triggered initial build
        count = await index.reindex()
    finally:
        await index.close()
        await engine.close()

    assert calls == [("index.reindexed", {"count": count, "vault": "work"})]


@pytest.mark.anyio
async def test_verify_emits_one_doctor_finding_event_per_finding(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    engine, index = await _open_index(
        tmp_path, on_event=lambda name, data: calls.append((name, data))
    )
    calls.clear()  # drop the open()-triggered initial build's index.reindexed
    index._doctor.verify = _fake_verify  # type: ignore[method-assign]
    try:
        await index.verify()
    finally:
        await index.close()
        await engine.close()

    assert [c[0] for c in calls] == ["doctor.finding", "doctor.finding"]
    assert calls[0][1] == {
        "code": "stale-lock",
        "severity": "warning",
        "detail": "found one",
        "vault": "work",
    }
    assert calls[1][1]["code"] == "temp-residue"


async def _fake_verify(_index: object) -> list[Finding]:
    return [
        Finding(code="stale-lock", severity="warning", detail="found one", fix="clear it"),
        Finding(code="temp-residue", severity="info", detail="found two", fix="sweep it"),
    ]


@pytest.mark.anyio
async def test_a_failing_hook_does_not_break_reindex(tmp_path: Path) -> None:
    def bad(_name: str, _data: dict[str, object]) -> None:
        raise RuntimeError("boom")

    engine, index = await _open_index(tmp_path, on_event=bad)
    try:
        count = await index.reindex()
    finally:
        await index.close()
        await engine.close()

    assert count >= 0  # did not raise; the failing hook was swallowed and logged


def test_backlog_drained_fires_only_once_the_backlog_is_actually_empty(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _StubEngine:
        name = "work"

    index = VaultIndex.__new__(VaultIndex)
    index._engine = _StubEngine()  # type: ignore[assignment]
    index._hub_event_hook = lambda name, data: calls.append((name, data))
    index.embed_status = lambda: _Status(pending=0)  # type: ignore[method-assign]

    index._emit_backlog_drained_if_empty(3)

    assert calls == [("index.embed_backlog_drained", {"embedded": 3, "vault": "work"})]


def test_backlog_drained_does_not_fire_when_the_backlog_is_still_nonempty(tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _StubEngine:
        name = "work"

    index = VaultIndex.__new__(VaultIndex)
    index._engine = _StubEngine()  # type: ignore[assignment]
    index._hub_event_hook = lambda name, data: calls.append((name, data))
    index.embed_status = lambda: _Status(pending=4)  # type: ignore[method-assign]

    index._emit_backlog_drained_if_empty(3)

    assert calls == []


class _Status:
    def __init__(self, *, pending: int) -> None:
        self.pending = pending
