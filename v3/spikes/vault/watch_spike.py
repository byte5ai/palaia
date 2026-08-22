#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "watchfiles"]
# ///
"""SPEC-003 Q2 — external-edit loop.

Modify a note on disk (simulating Obsidian) — does a watchfiles watcher pick
it up and reindex within ~2s? What debounce is sane? What happens with a
rapid rename+edit?

    uv run watch_spike.py --n 200

Runs three scenarios against a live watchfiles.watch() generator in a
background thread: (1) single content edit, (2) rapid rename+edit
(rename note A -> note A-renamed, then immediately edit its content), and
(3) a burst of 20 near-simultaneous edits, to see how many discrete
"changes" batches come out and with what latency from the edit to the
watcher observing it.
"""
from __future__ import annotations

import argparse
import json
import queue
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_vault  # noqa: E402
from watchfiles import watch  # noqa: E402


def watcher_thread(vault_dir: str, out_q: "queue.Queue", stop_event: threading.Event, debounce_ms: int):
    for changes in watch(vault_dir, debounce=debounce_ms, stop_event=stop_event):
        out_q.put((time.perf_counter(), changes))


def drain_first(out_q: "queue.Queue", timeout: float):
    try:
        return out_q.get(timeout=timeout)
    except queue.Empty:
        return None


def run(n: int, debounce_ms: int) -> dict:
    vault_dir = tempfile.mkdtemp(prefix="watch-vault-")
    gen_vault.write_vault(vault_dir, n, seed=3)

    out_q: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=watcher_thread, args=(vault_dir, out_q, stop_event, debounce_ms), daemon=True)
    t.start()
    time.sleep(0.5)  # let the watcher establish its baseline snapshot

    results: dict = {"n_notes": n, "debounce_ms": debounce_ms}

    # Scenario 1: single content edit.
    target = Path(vault_dir) / "note-000005.md"
    text = target.read_text(encoding="utf-8")
    t_edit = time.perf_counter()
    target.write_text(text + "\n<!-- edited -->\n", encoding="utf-8")
    seen = drain_first(out_q, timeout=5.0)
    results["scenario_1_single_edit"] = {
        "latency_seconds": (seen[0] - t_edit) if seen else None,
        "n_changes_in_batch": len(seen[1]) if seen else 0,
        "detected_within_2s": bool(seen and (seen[0] - t_edit) <= 2.0),
    }

    time.sleep(debounce_ms / 1000 + 0.3)
    while not out_q.empty():
        out_q.get_nowait()

    # Scenario 2: rapid rename + edit (simulate Obsidian rename-on-save).
    src = Path(vault_dir) / "note-000010.md"
    dst = Path(vault_dir) / "note-000010-renamed.md"
    t0 = time.perf_counter()
    src.rename(dst)
    dst.write_text(dst.read_text(encoding="utf-8") + "\n<!-- renamed+edited -->\n", encoding="utf-8")
    batches = []
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        item = drain_first(out_q, timeout=max(0.05, deadline - time.perf_counter()))
        if item is None:
            break
        batches.append(item)
    results["scenario_2_rename_plus_edit"] = {
        "n_batches_observed": len(batches),
        "first_batch_latency_seconds": (batches[0][0] - t0) if batches else None,
        "batches": [
            {"latency_seconds": ts - t0, "changes": [(str(kind), str(Path(p).name)) for kind, p in ch]}
            for ts, ch in batches
        ],
    }

    time.sleep(debounce_ms / 1000 + 0.3)
    while not out_q.empty():
        out_q.get_nowait()

    # Scenario 3: burst of 20 near-simultaneous edits.
    t0 = time.perf_counter()
    burst_files = [Path(vault_dir) / f"note-{i:06d}.md" for i in range(20, 40)]
    for f in burst_files:
        f.write_text(f.read_text(encoding="utf-8") + "\n<!-- burst -->\n", encoding="utf-8")
    batches = []
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        item = drain_first(out_q, timeout=max(0.05, deadline - time.perf_counter()))
        if item is None:
            break
        batches.append(item)
    n_changes_total = sum(len(ch) for _, ch in batches)
    results["scenario_3_burst_20_edits"] = {
        "n_batches_observed": len(batches),
        "n_changes_total_reported": n_changes_total,
        "first_batch_latency_seconds": (batches[0][0] - t0) if batches else None,
        "last_batch_latency_seconds": (batches[-1][0] - t0) if batches else None,
    }

    stop_event.set()
    t.join(timeout=3.0)
    shutil.rmtree(vault_dir, ignore_errors=True)
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--debounce-ms", type=int, default=200)
    args = ap.parse_args()
    report = run(args.n, args.debounce_ms)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
