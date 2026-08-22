#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "pygit2"]
# ///
"""SPEC-003 Q3 — git layer cost.

Auto-commit per write with attributed messages: measure cost per commit at
1k/10k notes (pygit2 vs subprocess git); does `git status` stay fast?
Is one-commit-per-write viable or is batching needed?

    uv run git_bench.py --n 1000 --backend pygit2
    uv run git_bench.py --n 1000 --backend subprocess
    uv run git_bench.py --n 1000 --backend pygit2 --mode batch

Each run creates a fresh temp git repo, writes --n toy notes one at a time,
and (per --mode) either commits after every single write ("percommit", the
architecture's default per MASTERPLAN §5.1) or once at the end ("batch").
Prints total/mean/p50/p95 commit latency, final repo/.git size, and
`git status` wall time in the resulting repo.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_vault  # noqa: E402
import pygit2  # noqa: E402

AUTHOR = pygit2.Signature("palaia-v3-spike", "spike@palaia.v3")


def du_bytes(path: str) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def run_pygit2(repo_dir: str, n: int, seed: int, mode: str) -> dict:
    pygit2.init_repository(repo_dir, bare=False)
    repo = pygit2.Repository(repo_dir)
    import random

    rng = random.Random(seed)
    commit_times: list[float] = []
    parent = None

    for i in range(n):
        permalink, text = gen_vault.make_note_text(i, n, rng)
        (Path(repo_dir) / f"{permalink}.md").write_text(text, encoding="utf-8")

        if mode == "batch" and i != n - 1:
            continue

        t0 = time.perf_counter()
        index = repo.index
        index.add_all()
        index.write()
        tree = index.write_tree()
        parents = [parent] if parent is not None else []
        msg = (
            f"chore(vault): batch write of {n} notes"
            if mode == "batch"
            else f"chore(vault): write {permalink} (agent=spike, client=git_bench)"
        )
        parent = repo.create_commit("HEAD", AUTHOR, AUTHOR, msg, tree, parents)
        commit_times.append(time.perf_counter() - t0)

    return {"commit_seconds": commit_times}


def run_subprocess(repo_dir: str, n: int, seed: int, mode: str) -> dict:
    subprocess.run(["git", "init", "-q", repo_dir], check=True)
    env_author = {
        "GIT_AUTHOR_NAME": "palaia-v3-spike",
        "GIT_AUTHOR_EMAIL": "spike@palaia.v3",
        "GIT_COMMITTER_NAME": "palaia-v3-spike",
        "GIT_COMMITTER_EMAIL": "spike@palaia.v3",
    }
    import os
    import random

    env = {**os.environ, **env_author}
    rng = random.Random(seed)
    commit_times: list[float] = []

    for i in range(n):
        permalink, text = gen_vault.make_note_text(i, n, rng)
        (Path(repo_dir) / f"{permalink}.md").write_text(text, encoding="utf-8")

        if mode == "batch" and i != n - 1:
            continue

        t0 = time.perf_counter()
        subprocess.run(["git", "-C", repo_dir, "add", "-A"], check=True, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        msg = (
            f"chore(vault): batch write of {n} notes"
            if mode == "batch"
            else f"chore(vault): write {permalink} (agent=spike, client=git_bench)"
        )
        subprocess.run(["git", "-C", repo_dir, "commit", "-q", "-m", msg], check=True, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        commit_times.append(time.perf_counter() - t0)

    return {"commit_seconds": commit_times}


def git_status_seconds(repo_dir: str, runs: int = 5) -> float:
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(["git", "-C", repo_dir, "status"], check=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def pctile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = min(len(s) - 1, int(len(s) * p))
    return s[idx]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--backend", choices=["pygit2", "subprocess"], required=True)
    ap.add_argument("--mode", choices=["percommit", "batch"], default="percommit")
    ap.add_argument("--keep", action="store_true", help="don't delete the repo afterwards")
    args = ap.parse_args()

    repo_dir = tempfile.mkdtemp(prefix=f"git-bench-{args.backend}-{args.mode}-")
    t0 = time.perf_counter()
    if args.backend == "pygit2":
        result = run_pygit2(repo_dir, args.n, args.seed, args.mode)
    else:
        result = run_subprocess(repo_dir, args.n, args.seed, args.mode)
    total = time.perf_counter() - t0

    ct = result["commit_seconds"]
    status_s = git_status_seconds(repo_dir)
    repo_size = du_bytes(repo_dir)
    git_size = du_bytes(str(Path(repo_dir) / ".git"))

    n_commits = subprocess.run(
        ["git", "-C", repo_dir, "rev-list", "--count", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    report = {
        "backend": args.backend,
        "mode": args.mode,
        "n_notes": args.n,
        "n_commits": int(n_commits),
        "total_seconds": total,
        "mean_commit_ms": (statistics.mean(ct) * 1000) if ct else None,
        "p50_commit_ms": pctile(ct, 0.50) * 1000 if ct else None,
        "p95_commit_ms": pctile(ct, 0.95) * 1000 if ct else None,
        "max_commit_ms": (max(ct) * 1000) if ct else None,
        "git_status_median_seconds": status_s,
        "repo_size_bytes": repo_size,
        "git_dir_size_bytes": git_size,
        "repo_dir": repo_dir,
    }
    print(json.dumps(report, indent=2))

    if not args.keep:
        shutil.rmtree(repo_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
