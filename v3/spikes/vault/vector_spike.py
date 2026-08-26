#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "fastembed", "sqlite-vec"]
# ///
"""SPEC-003 Q4 — vector search spike.

fastembed + sqlite-vec on the same toy vault — cold-start time, per-note
embed cost, hybrid merge sketch.

    uv run vector_spike.py --n 1000
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_vault  # noqa: E402
import grammar  # noqa: E402
import index_lib  # noqa: E402
import sqlite_vec  # noqa: E402

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # fastembed default, per research/basic-memory.md §3


def entity_text(entity) -> str:
    observations = "\n".join(o.content for o in entity.observations)
    return entity.title + "\n" + entity.body + "\n" + observations


def run(n: int) -> dict:
    vault_dir = tempfile.mkdtemp(prefix="vec-vault-")
    db_path = str(Path(vault_dir).with_name(Path(vault_dir).name + "-index.db"))

    gen_vault.write_vault(vault_dir, n, seed=7)
    build_stats = index_lib.build_index(vault_dir, db_path)

    t0 = time.perf_counter()
    from fastembed import TextEmbedding

    model = TextEmbedding(model_name=MODEL_NAME)
    # includes first-run ONNX model load (+ download if not cached)
    t_cold_start = time.perf_counter() - t0

    files = index_lib.list_vault_files(vault_dir)
    entities = [grammar.parse_file(f, vault_dir) for f in files]
    texts = [entity_text(e) for e in entities]

    t0 = time.perf_counter()
    embeddings = list(model.embed(texts))
    t_embed_all = time.perf_counter() - t0
    dim = len(embeddings[0])

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(f"CREATE VIRTUAL TABLE vec_entities USING vec0(embedding float[{dim}])")
    # sqlite-vec vec0 rowids must be assigned explicitly to align with entities.
    conn.execute(
        "CREATE TABLE vec_rowid_map (rowid_ INTEGER PRIMARY KEY, permalink TEXT NOT NULL)"
    )

    t0 = time.perf_counter()
    for i, (entity, emb) in enumerate(zip(entities, embeddings, strict=True)):
        conn.execute(
            "INSERT INTO vec_entities(rowid, embedding) VALUES (?, ?)",
            (i, sqlite_vec.serialize_float32(emb.tolist())),
        )
        conn.execute(
            "INSERT INTO vec_rowid_map(rowid_, permalink) VALUES (?, ?)", (i, entity.permalink)
        )
    conn.commit()
    t_insert_vec = time.perf_counter() - t0

    # Hybrid merge sketch: run one query both ways and merge by simple
    # weighted rank-fusion (not a final ranking design — SPEC-104 owns that).
    query_text = "synchronous writes and files as source of truth"
    t0 = time.perf_counter()
    q_emb = list(model.embed([query_text]))[0]
    t_query_embed = time.perf_counter() - t0

    t0 = time.perf_counter()
    vec_rows = conn.execute(
        """
        SELECT m.permalink, v.distance
        FROM (
            SELECT rowid, distance FROM vec_entities
            WHERE embedding MATCH ? ORDER BY distance LIMIT 10
        ) v
        JOIN vec_rowid_map m ON m.rowid_ = v.rowid
        """,
        (sqlite_vec.serialize_float32(q_emb.tolist()),),
    ).fetchall()
    t_vec_search = time.perf_counter() - t0

    t0 = time.perf_counter()
    fts_rows = conn.execute(
        "SELECT permalink, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 10",
        ('"' + query_text.replace('"', ' ') + '"',),
    ).fetchall()
    # Phrase queries rarely hit in free prose; fall back to OR-of-terms for the sketch.
    if not fts_rows:
        or_query = " OR ".join(w for w in query_text.split() if w.isalpha())
        fts_rows = conn.execute(
            "SELECT permalink, rank FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT 10",
            (or_query,),
        ).fetchall()
    t_fts_search = time.perf_counter() - t0

    # Rank-fusion sketch: score = 1/(rank_fts+1) + 1/(rank_vec+1), higher wins.
    fts_rank = {p: i for i, (p, _r) in enumerate(fts_rows)}
    vec_rank = {p: i for i, (p, _d) in enumerate(vec_rows)}
    fused: dict[str, float] = {}
    for p in set(fts_rank) | set(vec_rank):
        fused[p] = 1.0 / (fts_rank.get(p, 999) + 1) + 1.0 / (vec_rank.get(p, 999) + 1)
    hybrid_top = sorted(fused.items(), key=lambda kv: -kv[1])[:10]

    conn.close()
    db_size = Path(db_path).stat().st_size

    report = {
        "n_notes": n,
        "model": MODEL_NAME,
        "embedding_dim": dim,
        "fts_build": build_stats,
        "cold_start_seconds": t_cold_start,
        "embed_all_seconds": t_embed_all,
        "embed_per_note_ms": (t_embed_all / n) * 1000,
        "vec_insert_seconds": t_insert_vec,
        "vec_insert_per_note_ms": (t_insert_vec / n) * 1000,
        "query_embed_ms": t_query_embed * 1000,
        "vec_search_ms": t_vec_search * 1000,
        "fts_search_ms": t_fts_search * 1000,
        "db_size_bytes_with_vectors": db_size,
        "fts_only_db_size_bytes": build_stats["db_size_bytes"],
        "vec_top10": [p for p, _ in vec_rows],
        "fts_top10": [p for p, _ in fts_rows],
        "hybrid_top10_rank_fusion": [p for p, _ in hybrid_top],
    }

    shutil.rmtree(vault_dir, ignore_errors=True)
    Path(db_path).unlink(missing_ok=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    report = run(args.n)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
