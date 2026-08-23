"""Embedding model / batch-size benchmark.

SPEC-104 makes this a deliverable, not a nicety: the SPEC-003 spike measured
**437 ms/note** with ``BAAI/bge-small-en-v1.5`` in a serial loop and closed
with "investigate fastembed batch-size/thread tuning or a smaller/faster model
before committing to it as *the* default". This module is that investigation,
kept in-tree so the number can be re-measured on the hardware that matters
instead of being quoted from a PR forever.

Run it against the golden vault (or any vault):

    uv run python -m palaia_hub.index.bench --notes 200
    uv run python -m palaia_hub.index.bench --model BAAI/bge-small-en-v1.5 --batch 1,8,32

It reports, per (model, batch size): model load time, total embed time,
ms/note, and the embedding dimension — plus the FTS-only index build time on
the same corpus, because the ratio between the two is the whole argument for
embedding asynchronously.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Sequence
from pathlib import Path

from .embeddings import EmbeddingConfig, chunk_text, embeddable_text

#: Models worth comparing: the spike's default and the smaller/faster
#: alternative, both 384-dimensional so the index schema is unaffected.
CANDIDATE_MODELS: tuple[str, ...] = (
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
)

DEFAULT_BATCHES: tuple[int, ...] = (1, 8, 32, 64)


def collect_texts(vault: Path, limit: int) -> list[str]:
    """Chunk up to ``limit`` notes of ``vault`` the way the index would."""
    from palaia_hub.vault.parse import parse_note

    texts: list[str] = []
    for path in sorted(vault.rglob("*.md")):
        if any(part in {".git", ".palaia", ".obsidian"} for part in path.parts):
            continue
        relative = str(path.relative_to(vault))
        parsed = parse_note(path.read_text(encoding="utf-8"), relative)
        note_text = embeddable_text(
            parsed.title, parsed.body, [obs.text for obs in parsed.observations]
        )
        texts.extend(chunk.text for chunk in chunk_text(note_text))
        if len(texts) >= limit:
            break
    return texts[:limit]


def bench_model(model: str, texts: Sequence[str], batches: Sequence[int]) -> list[dict[str, float]]:
    """Time ``model`` over ``texts`` at each batch size."""
    from fastembed import TextEmbedding

    rows: list[dict[str, float]] = []
    started = time.perf_counter()
    embedder = TextEmbedding(model_name=model)
    load_seconds = time.perf_counter() - started
    dim = len(next(iter(embedder.embed(["dimension probe"]))))

    for batch in batches:
        started = time.perf_counter()
        vectors = list(embedder.embed(list(texts), batch_size=batch))
        elapsed = time.perf_counter() - started
        rows.append(
            {
                "batch_size": float(batch),
                "chunks": float(len(vectors)),
                "seconds": elapsed,
                "ms_per_chunk": (elapsed / len(vectors)) * 1000 if vectors else 0.0,
                "load_seconds": load_seconds,
                "dim": float(dim),
            }
        )
    return rows


def bench_fts(texts: Sequence[str]) -> dict[str, float]:
    """Time an FTS5 insert of the same texts — the async-mandate baseline."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE fts USING fts5(text)")
    started = time.perf_counter()
    conn.executemany("INSERT INTO fts(text) VALUES (?)", [(text,) for text in texts])
    conn.commit()
    elapsed = time.perf_counter() - started
    conn.close()
    return {
        "chunks": float(len(texts)),
        "seconds": elapsed,
        "ms_per_chunk": (elapsed / len(texts)) * 1000 if texts else 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    default_vault = (
        Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "golden-vault" / "work"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=default_vault)
    parser.add_argument("--notes", type=int, default=120, help="max chunks to embed")
    parser.add_argument("--model", action="append", dest="models", default=None)
    parser.add_argument("--batch", default=",".join(str(b) for b in DEFAULT_BATCHES))
    args = parser.parse_args(argv)

    models = args.models or list(CANDIDATE_MODELS)
    batches = [int(part) for part in str(args.batch).split(",") if part.strip()]
    texts = collect_texts(args.vault, args.notes)
    if not texts:
        parser.error(f"no notes found under {args.vault}")

    report: dict[str, object] = {
        "vault": str(args.vault),
        "chunks": len(texts),
        "mean_chunk_chars": round(statistics.mean(len(text) for text in texts), 1),
        "default_config": {
            "model": EmbeddingConfig().model,
            "batch_size": EmbeddingConfig().batch_size,
        },
        "fts_baseline": bench_fts(texts),
        "models": {model: bench_model(model, texts, batches) for model in models},
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
