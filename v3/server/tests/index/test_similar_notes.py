"""Issue #187: "this note resembles an existing one", measured honestly.

The warning a ``write``/``capture`` result carries is only as good as the
number behind it. Issue #481 is the cautionary tale: a relative score (BM25,
rank fusion) orders one query's hits but says nothing absolute, so holding it
against a fixed threshold is meaningless. These tests pin that the number here
is a **true cosine similarity** — computed independently from the embedder's
own vectors and compared — and then walk the signal up through the vault
adapter (threshold, exclusions, never failing a write) to the MCP tool result
an agent actually reads.

The embedder is the deterministic hashed bag-of-words stub, so "similar" here
means lexical overlap — enough to prove the plumbing and the arithmetic. The
real model's score ranges, which the default threshold is calibrated on, are
recorded next to :data:`palaia_hub.nudges.DEFAULT_SIMILAR_NOTE_THRESHOLD`.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from stub_embedder import StubEmbedder

from palaia_hub.gateway import wiring
from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.guidance import GUIDANCE_HEADING
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, NoteSimilarity, SearchFilters, embeddable_text

pytestmark = pytest.mark.anyio

HEALTH_TITLE = "Health endpoint"
HEALTH_BODY = "GET /health returns 200 when the gateway service is up and serving."


def _stub_config() -> EmbeddingConfig:
    return EmbeddingConfig(enabled=True, model="stub/hashed-bow", batch_size=64)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def _vault(tmp_path: Path, open_index: Any, *, dim: int = 256) -> Any:
    """A small vault: one health note, one unrelated note, one meta note,
    one review proposal — every note embedded."""
    embedder = StubEmbedder(dim=dim)
    engine, index = await open_index(tmp_path / "work", embedding=_stub_config(), embedder=embedder)
    await engine.write_note(
        "ops/health-endpoint.md",
        title=HEALTH_TITLE,
        body=HEALTH_BODY + "\n",
        frontmatter={"type": "note"},
    )
    await engine.write_note(
        "people/lunch.md",
        title="Team lunch",
        body="Friday lunch is at noon in the kitchen.\n",
        frontmatter={"type": "note"},
    )
    await engine.write_note(
        "review/health-proposal.md",
        title="Health endpoint",
        body=HEALTH_BODY + "\n",
        frontmatter={"type": "proposal", "status": "proposed"},
    )
    await index.drain_embeddings()
    assert index.status().embeds.pending == 0
    return engine, index, embedder


# --- the index: a true cosine similarity -------------------------------------


async def test_the_similarity_is_the_cosine_of_the_two_embeddings(
    tmp_path: Path, open_index: Any
) -> None:
    """The load-bearing test: recompute the cosine from the embedder's own
    vectors and require the index to report exactly that — not 1/(1+L2), not
    a rank, not a fused score."""
    _, index, embedder = await _vault(tmp_path, open_index)
    title, body = "Health endpoint", "GET /health returns 404 since the gateway migration."

    found = await index.similar_notes(title, body, limit=5)

    by_permalink = {note.permalink: note for note in found}
    assert "ops/health-endpoint" in by_permalink
    probe, stored = embedder.embed(
        [embeddable_text(title, body, ()), embeddable_text(HEALTH_TITLE, HEALTH_BODY, ())]
    )
    expected = _cosine(probe, stored)
    assert 0.2 < expected < 0.95, "the fixture should be a partial overlap"
    assert by_permalink["ops/health-endpoint"].similarity == pytest.approx(expected, abs=1e-5)


async def test_identical_text_is_similarity_one(tmp_path: Path, open_index: Any) -> None:
    _, index, _ = await _vault(tmp_path, open_index)
    found = await index.similar_notes(HEALTH_TITLE, HEALTH_BODY, limit=1)
    assert found[0].similarity == pytest.approx(1.0, abs=1e-5)


async def test_results_are_best_first_one_per_note_and_capped(
    tmp_path: Path, open_index: Any
) -> None:
    _, index, _ = await _vault(tmp_path, open_index)
    found = await index.similar_notes(HEALTH_TITLE, HEALTH_BODY, limit=2)
    assert len(found) == 2
    assert found[0].similarity >= found[1].similarity
    assert len({note.permalink for note in found}) == 2
    assert all(isinstance(note, NoteSimilarity) for note in found)


async def test_the_note_itself_and_filtered_types_are_left_out(
    tmp_path: Path, open_index: Any
) -> None:
    _, index, _ = await _vault(tmp_path, open_index)
    unfiltered = {
        n.permalink for n in await index.similar_notes(HEALTH_TITLE, HEALTH_BODY, limit=5)
    }
    assert {"ops/health-endpoint", "review/health-endpoint"} <= unfiltered, "fixture sanity"
    found = await index.similar_notes(
        HEALTH_TITLE,
        HEALTH_BODY,
        limit=5,
        filters=SearchFilters(exclude_types=("meta", "proposal")),
        exclude=("ops/health-endpoint",),
    )
    permalinks = {note.permalink for note in found}
    assert "ops/health-endpoint" not in permalinks
    assert "review/health-endpoint" not in permalinks
    assert all(note.type not in ("meta", "proposal") for note in found)


async def test_no_embeddings_means_no_answer_not_a_lexical_guess(
    tmp_path: Path, open_index: Any
) -> None:
    """Issue #481's lesson: without vectors there is no similarity to
    report, and full-text rank is not an acceptable stand-in."""
    engine, index = await open_index(tmp_path / "work")  # embeddings off
    await engine.write_note(
        "ops/health.md", title=HEALTH_TITLE, body=HEALTH_BODY, frontmatter={"type": "note"}
    )
    assert await index.similar_notes(HEALTH_TITLE, HEALTH_BODY) == []


async def test_nothing_embedded_yet_means_no_answer(tmp_path: Path, open_index: Any) -> None:
    engine, index = await open_index(
        tmp_path / "work", embedding=_stub_config(), embedder=StubEmbedder()
    )
    await engine.write_note(
        "ops/health.md", title=HEALTH_TITLE, body=HEALTH_BODY, frontmatter={"type": "note"}
    )
    assert index.status().embeds.ready == 0
    assert await index.similar_notes(HEALTH_TITLE, HEALTH_BODY) == []


# --- the vault adapter: threshold, exclusions, never failing -------------------


async def test_the_adapter_applies_its_threshold(tmp_path: Path, open_index: Any) -> None:
    engine, index, _ = await _vault(tmp_path, open_index)
    body = "GET /health returns 404 since the gateway migration."
    permissive = EngineVaultService(engine, index, similar_note_threshold=0.5)
    strict = EngineVaultService(engine, index, similar_note_threshold=0.99)

    hits = await permissive.similar_notes(HEALTH_TITLE, body)
    assert [hit.permalink for hit in hits] == ["ops/health-endpoint"]
    assert 0.5 <= hits[0].similarity < 0.99
    assert await strict.similar_notes(HEALTH_TITLE, body) == []


async def test_the_adapter_never_points_at_meta_or_proposals(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index, _ = await _vault(tmp_path, open_index)
    service = EngineVaultService(engine, index, similar_note_threshold=0.5)
    hits = await service.similar_notes(HEALTH_TITLE, HEALTH_BODY, exclude="ops/other")
    permalinks = {hit.permalink for hit in hits}
    assert "ops/health-endpoint" in permalinks
    assert "review/health-endpoint" not in permalinks
    assert "meta/vault" not in permalinks


async def test_the_check_can_be_switched_off_and_needs_an_index(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index, _ = await _vault(tmp_path, open_index)
    assert (
        await EngineVaultService(engine, index, similar_note_threshold=None).similar_notes(
            HEALTH_TITLE, HEALTH_BODY
        )
        == []
    )
    assert await EngineVaultService(engine).similar_notes(HEALTH_TITLE, HEALTH_BODY) == []


async def test_a_slow_check_is_abandoned_not_waited_for(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first check after a restart may have to load the model; the
    write's result must not wait on that."""
    engine, index, _ = await _vault(tmp_path, open_index)
    monkeypatch.setattr(wiring, "SIMILAR_NOTES_TIMEOUT_SECONDS", 0.05)
    release = asyncio.Event()

    async def slow(*_: Any, **__: Any) -> list[NoteSimilarity]:
        await release.wait()
        return [NoteSimilarity(permalink="ops/x", title="X", similarity=1.0)]

    monkeypatch.setattr(index, "similar_notes", slow)
    service = EngineVaultService(engine, index)
    assert await asyncio.wait_for(service.similar_notes("t", "b"), timeout=2.0) == []
    release.set()
    await asyncio.sleep(0)


async def test_a_failing_check_answers_nothing(
    tmp_path: Path, open_index: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, index, _ = await _vault(tmp_path, open_index)

    async def broken(*_: Any, **__: Any) -> list[NoteSimilarity]:
        raise RuntimeError("vec table went away")

    monkeypatch.setattr(index, "similar_notes", broken)
    assert await EngineVaultService(engine, index).similar_notes("t", "b") == []


# --- end to end: the write tool over a real vault ------------------------------


async def test_writing_a_contradicting_note_names_the_existing_one(
    tmp_path: Path, open_index: Any
) -> None:
    """Issue #187 end to end: real engine, real index, real vectors, the MCP
    tool an agent calls. The write lands; the result names the note it may
    contradict."""
    engine, index, _ = await _vault(tmp_path, open_index)
    service = EngineVaultService(engine, index, similar_note_threshold=0.5)
    server = build_vault_server(VaultMountConfig(key="work", name="work", purpose="Test."), service)
    async with Client(server) as client:
        result = await client.call_tool(
            "write",
            {
                "title": "Health endpoint status",
                "body": "GET /health returns 404 when the gateway service is up.",
                "folder": "ops",
            },
        )
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["permalink"] == "ops/health-endpoint-status"
    (line,) = result.structured_content["guidance"]
    assert f"'{HEALTH_TITLE}' (ops/health-endpoint)" in line
    assert "ops/health-endpoint-status" not in line, "a note never resembles itself"
    assert GUIDANCE_HEADING in result.content[0].text  # type: ignore[union-attr]
    assert (await service.read("ops/health-endpoint-status")).title == "Health endpoint status"


async def test_writing_an_unrelated_note_carries_no_guidance(
    tmp_path: Path, open_index: Any
) -> None:
    engine, index, _ = await _vault(tmp_path, open_index)
    service = EngineVaultService(engine, index)
    server = build_vault_server(VaultMountConfig(key="work", name="work", purpose="Test."), service)
    async with Client(server) as client:
        result = await client.call_tool(
            "write",
            {"title": "Quarterly budget", "body": "Marketing spend rises by ten percent in Q4."},
        )
    assert result.structured_content is not None
    assert "guidance" not in result.structured_content
