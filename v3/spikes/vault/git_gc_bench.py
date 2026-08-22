#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""SPEC-003 Q3 addendum — does `git gc` recover the loose-object bloat that
one-commit-per-write leaves behind?

    uv run git_gc_bench.py --repo /path/to/repo [--aggressive]

Reports .git size before/after gc and how long gc took.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def du_bytes(path: str) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--aggressive", action="store_true")
    args = ap.parse_args()

    before = du_bytes(str(Path(args.repo) / ".git"))
    cmd = ["git", "-C", args.repo, "gc"] + (["--aggressive"] if args.aggressive else [])
    t0 = time.perf_counter()
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    gc_seconds = time.perf_counter() - t0
    after = du_bytes(str(Path(args.repo) / ".git"))

    print(json.dumps({
        "repo": args.repo,
        "aggressive": args.aggressive,
        "git_dir_bytes_before": before,
        "git_dir_bytes_after": after,
        "gc_seconds": gc_seconds,
        "shrink_ratio": before / after if after else None,
    }, indent=2))


if __name__ == "__main__":
    main()
