#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""SPEC-003 Q1 — round-trip proof.

write notes -> parse -> index (SQLite FTS5) -> search -> delete DB ->
rebuild from files -> identical search results?

    uv run round_trip.py --n 2000 --seed 42 [--out /tmp/rt-vault]

Prints per-query result sets before/after rebuild and a PASS/FAIL verdict,
plus build timings and sizes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_vault  # noqa: E402
import index_lib  # noqa: E402

QUERIES = [
    "vault-format",
    "authentication",
    "recall-scoring",
    "synchronous",
    "decision",
    "note-000042",
]


def run(n: int, seed: int, out_dir: str | None) -> dict:
    cleanup = out_dir is None
    vault_dir = out_dir or tempfile.mkdtemp(prefix="rt-vault-")
    db_path = str(Path(vault_dir).with_name(Path(vault_dir).name + "-index.db"))

    t0 = time.perf_counter()
    gen_vault.write_vault(vault_dir, n, seed)
    t_gen = time.perf_counter()

    stats_1 = index_lib.build_index(vault_dir, db_path)
    results_1 = {q: index_lib.search(db_path, q) for q in QUERIES}

    Path(db_path).unlink()

    stats_2 = index_lib.build_index(vault_dir, db_path)
    results_2 = {q: index_lib.search(db_path, q) for q in QUERIES}

    identical = results_1 == results_2
    t_end = time.perf_counter()

    report = {
        "n_notes_requested": n,
        "seed": seed,
        "vault_dir": vault_dir,
        "generate_seconds": t_gen - t0,
        "build_1": stats_1,
        "build_2_after_delete": stats_2,
        "queries": QUERIES,
        "results_before_rebuild": results_1,
        "results_after_rebuild": results_2,
        "identical_search_results": identical,
        "total_wall_seconds": t_end - t0,
    }

    if cleanup:
        shutil.rmtree(vault_dir, ignore_errors=True)
        Path(db_path).unlink(missing_ok=True)

    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=None, help="keep the generated vault here instead of a throwaway tmpdir")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON only")
    args = ap.parse_args()

    report = run(args.n, args.seed, args.out)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print(f"generated {report['n_notes_requested']} notes in {report['generate_seconds']:.3f}s -> {report['vault_dir']}")
    b1, b2 = report["build_1"], report["build_2_after_delete"]
    print(
        f"build #1 (fresh):        {b1['n_entities']} entities, {b1['n_observations']} obs, "
        f"{b1['n_relations']} rel, {b1['n_parse_errors']} parse errors, "
        f"{b1['total_seconds']:.3f}s, db={b1['db_size_bytes']/1024:.1f} KiB"
    )
    print(
        f"build #2 (after rm db):  {b2['n_entities']} entities, {b2['n_observations']} obs, "
        f"{b2['n_relations']} rel, {b2['n_parse_errors']} parse errors, "
        f"{b2['total_seconds']:.3f}s, db={b2['db_size_bytes']/1024:.1f} KiB"
    )
    print()
    for q in report["queries"]:
        before = report["results_before_rebuild"][q]
        after = report["results_after_rebuild"][q]
        mark = "==" if before == after else "!="
        print(f'  query {q!r:24s} before={before!r} {mark} after={after!r}')
    print()
    verdict = "PASS" if report["identical_search_results"] else "FAIL"
    print(f"identical_search_results: {report['identical_search_results']}  [{verdict}]")
    print(f"total wall time: {report['total_wall_seconds']:.3f}s")


if __name__ == "__main__":
    main()
