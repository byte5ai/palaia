#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Post-kill inspector used by kill_test.sh (SPEC-003 Q5).

Given a vault directory that a writer.py process was SIGKILLed inside of,
checks:
  - are there stray temp files (expected/harmless — a write-in-progress
    that never got its atomic rename)?
  - is every *.md file on disk fully parseable (no truncation/corruption)?
  - is there a stale .git/index.lock (pygit2/libgit2 leaves one if killed
    mid index-write)?
  - does `git status` work as-is, and if not, is removing the stale lock
    sufficient to recover (no other repair needed)?
  - can the SQLite index be rebuilt from files afterwards, and does the
    resulting entity count match the number of valid .md files on disk?
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grammar  # noqa: E402
import index_lib  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault-dir", required=True)
    ap.add_argument("--trial", type=int, required=True)
    ap.add_argument("--delay", type=float, required=True)
    args = ap.parse_args()

    vault_dir = Path(args.vault_dir)
    md_files = sorted(vault_dir.glob("*.md"))
    tmp_files = sorted(
        p for p in vault_dir.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")
    )

    parse_failures = []
    for p in md_files:
        try:
            grammar.parse_file(str(p), str(vault_dir))
        except grammar.ParseError as exc:
            parse_failures.append({"file": p.name, "error": str(exc)})
        except Exception as exc:  # any other exception is itself a finding
            parse_failures.append({"file": p.name, "error": f"unexpected: {exc!r}"})

    zero_byte_files = [p.name for p in md_files if p.stat().st_size == 0]

    index_lock = vault_dir / ".git" / "index.lock"
    lock_present = index_lock.exists()

    status_before = subprocess.run(
        ["git", "-C", str(vault_dir), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    status_before_ok = status_before.returncode == 0

    recovery_needed = False
    recovery_sufficient = None
    if lock_present:
        recovery_needed = True
        index_lock.unlink()
        status_after = subprocess.run(
            ["git", "-C", str(vault_dir), "status", "--porcelain"],
            capture_output=True, text=True,
        )
        recovery_sufficient = status_after.returncode == 0

    progress_log = vault_dir / "progress.log"
    last_confirmed = None
    n_confirmed_lines = 0
    if progress_log.exists():
        lines = progress_log.read_text(encoding="utf-8").strip().splitlines()
        n_confirmed_lines = len(lines)
        if lines:
            last_confirmed = lines[-1].split("\t")

    db_path = tempfile.mktemp(suffix=".db")
    rebuild_error = None
    build_stats = None
    try:
        build_stats = index_lib.build_index(str(vault_dir), db_path)
    except Exception as exc:  # noqa: BLE001
        rebuild_error = repr(exc)
    finally:
        Path(db_path).unlink(missing_ok=True)

    report = {
        "trial": args.trial,
        "kill_delay_seconds": args.delay,
        "n_md_files": len(md_files),
        "n_stray_tmp_files": len(tmp_files),
        "stray_tmp_files": [p.name for p in tmp_files],
        "n_parse_failures": len(parse_failures),
        "parse_failures": parse_failures,
        "n_zero_byte_md_files": len(zero_byte_files),
        "git_index_lock_present": lock_present,
        "git_status_ok_immediately": status_before_ok,
        "recovery_needed": recovery_needed,
        "recovery_sufficient_lock_removal_only": recovery_sufficient,
        "n_confirmed_writes_in_progress_log": n_confirmed_lines,
        "last_confirmed_write": last_confirmed,
        "rebuild_error": rebuild_error,
        "rebuild_n_entities": build_stats["n_entities"] if build_stats else None,
        "rebuild_matches_md_file_count": (
            build_stats["n_entities"] == len(md_files) if build_stats else None
        ),
        "vault_corrupt": bool(parse_failures) or bool(zero_byte_files) or bool(rebuild_error),
    }
    print(json.dumps(report))


if __name__ == "__main__":
    main()
