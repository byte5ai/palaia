#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "pygit2"]
# ///
"""Writer used by kill_test.sh (SPEC-003 Q5).

Loops forever (until killed) writing notes into --vault-dir using the
architecture's promised write protocol: write to a temp file in the same
directory, fsync, os.replace() (atomic rename) into place, THEN git-commit
the change. After each fully-completed iteration it appends the note's
permalink to progress.log so the checker can tell how many writes were
confirmed complete before the kill landed.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_vault  # noqa: E402
import pygit2  # noqa: E402

AUTHOR = pygit2.Signature("palaia-v3-spike", "spike@palaia.v3")


def atomic_write(vault_dir: Path, permalink: str, text: str) -> Path:
    final_path = vault_dir / f"{permalink}.md"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{permalink}.", suffix=".tmp", dir=str(vault_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, final_path)  # atomic on POSIX
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return final_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-dir", required=True)
    ap.add_argument("--n", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=99)
    args = ap.parse_args()

    vault_dir = Path(args.vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)
    pygit2.init_repository(str(vault_dir), bare=False)
    repo = pygit2.Repository(str(vault_dir))
    progress_path = vault_dir / "progress.log"

    import random

    rng = random.Random(args.seed)
    parent = None
    if not repo.head_is_unborn:
        parent = repo.head.target

    with open(progress_path, "a", encoding="utf-8") as progress:
        for i in range(args.n):
            permalink, text = gen_vault.make_note_text(i, args.n, rng)
            atomic_write(vault_dir, permalink, text)

            index = repo.index
            index.add_all()
            index.write()
            tree = index.write_tree()
            parents = [parent] if parent is not None else []
            parent = repo.create_commit(
                "HEAD", AUTHOR, AUTHOR,
                f"chore(vault): write {permalink} (agent=spike, client=kill_test)",
                tree, parents,
            )
            progress.write(f"{i}\t{permalink}\t{time.time()}\n")
            progress.flush()


if __name__ == "__main__":
    main()
