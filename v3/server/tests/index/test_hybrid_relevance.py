"""Does hybrid actually beat pure FTS? Measured, not assumed.

SPEC-104 acceptance criterion: "hybrid beats pure FTS on the SPEC-003 toy-vault
relevance battery (recall@5 measured, documented in PR)". The battery below is
written *against the golden vault* and deliberately phrased the way a person
asks a question rather than the way the note is written — which is exactly the
case lexical search cannot serve and a paraphrase-aware embedding can.

This is the only test that loads a real embedding model. It is skipped when
fastembed or the model cache is unavailable (offline CI), so the numbers in
the PR come from a run where it did execute; run it explicitly with::

    uv run pytest server/tests/index/test_hybrid_relevance.py -s
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from palaia_hub.index import EmbeddingConfig
from palaia_hub.index.embeddings import EmbedderUnavailableError, build_embedder

pytestmark = pytest.mark.anyio

#: query -> the permalink that should be in the top 5. Every query avoids the
#: target note's distinctive words where possible.
RELEVANCE_BATTERY: dict[str, str] = {
    "who leads work on the vault and owns its doctor": "people/alice-novak",
    "how should I phrase the subject of a git commit": "rules/how-to-write-commit-messages",
    "which database stores the searchable projection": "decisions/use-sqlite-for-index",
    "what do I do first when the hub is destroying data": "processes/incident-response",
    "never put credentials or secret tokens in a note": "rules/secrets-handling",
    "assembling context by traversing the knowledge graph": "projects/recall-engine",
    "keeping each customer's notes physically apart": "decisions/physical-vault-isolation",
    "how long do we keep old data around": "rules/data-retention",
    "steps for bringing a new customer on board": "processes/onboarding-a-new-client",
    "what licence did we settle on": "decisions/mit-license",
}

_TOP_K = 5


def _rank(ranked: list[str], expected: str) -> str:
    """1-based position of ``expected`` in ``ranked``, or ``-`` if absent."""
    return str(ranked.index(expected) + 1) if expected in ranked else "-"


def _recall_at_k(found: dict[str, list[str]], k: int = _TOP_K) -> float:
    hits = sum(
        1 for query, expected in RELEVANCE_BATTERY.items() if expected in found[query][:k]
    )
    return hits / len(RELEVANCE_BATTERY)


@pytest.fixture(scope="module")
def real_embedder() -> Any:
    pytest.importorskip("fastembed", reason="the embeddings extra is not installed")
    try:
        return build_embedder(EmbeddingConfig())
    except EmbedderUnavailableError as exc:  # pragma: no cover - offline CI
        pytest.skip(f"embedding model unavailable: {exc}")


async def test_hybrid_beats_pure_fts_on_recall_at_5(
    golden_work_vault: Path, open_index: Any, real_embedder: Any, capsys: Any
) -> None:
    _, index = await open_index(
        golden_work_vault,
        embedding=EmbeddingConfig(enabled=True),
        embedder=real_embedder,
    )
    embedded = await index.drain_embeddings(timeout=600.0)
    assert embedded > 0
    assert index.status().embeds.pending == 0

    fts: dict[str, list[str]] = {}
    hybrid: dict[str, list[str]] = {}
    vector: dict[str, list[str]] = {}
    for query in RELEVANCE_BATTERY:
        fts[query] = [hit.permalink for hit in (await index.search(query, mode="fts")).hits]
        vector_results = await index.search(query, mode="vector")
        assert not vector_results.degraded
        vector[query] = [hit.permalink for hit in vector_results.hits]
        hybrid_results = await index.search(query, mode="hybrid")
        assert hybrid_results.effective_mode == "hybrid"
        hybrid[query] = [hit.permalink for hit in hybrid_results.hits]

    fts_recall = _recall_at_k(fts)
    vector_recall = _recall_at_k(vector)
    hybrid_recall = _recall_at_k(hybrid)

    with capsys.disabled():
        print(
            f"\nrecall@{_TOP_K} over {len(RELEVANCE_BATTERY)} queries "
            f"(model {real_embedder.name}, dim {real_embedder.dim}): "
            f"fts={fts_recall:.2f} vector={vector_recall:.2f} hybrid={hybrid_recall:.2f}"
        )
        for query, expected in RELEVANCE_BATTERY.items():
            print(
                f"  fts={_rank(fts[query], expected):>3} "
                f"vec={_rank(vector[query], expected):>3} "
                f"hyb={_rank(hybrid[query], expected):>3}  {query}"
            )

    assert hybrid_recall > fts_recall, (
        f"hybrid recall@{_TOP_K} {hybrid_recall:.2f} did not beat FTS {fts_recall:.2f}"
    )


async def test_hybrid_keeps_the_exact_lexical_hits_fts_finds(
    golden_work_vault: Path, open_index: Any, real_embedder: Any
) -> None:
    """Fusion must not *lose* the precise hits — the other half of "hybrid"."""
    _, index = await open_index(
        golden_work_vault,
        embedding=EmbeddingConfig(enabled=True),
        embedder=real_embedder,
    )
    await index.drain_embeddings(timeout=600.0)
    for query, expected in (
        ("API Gateway", "projects/api-gateway"),
        ("Alice Novak", "people/alice-novak"),
        ("rate limit", "inbox/rate-limit-decision-from-pr-review"),
    ):
        results = await index.search(query, mode="hybrid", limit=5)
        assert expected in {hit.permalink for hit in results.hits}, query
