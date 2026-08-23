"""Write-burst worker for the kill -9 test (SPEC-003 Q5 pattern).

Writes notes through the real :class:`~palaia_hub.vault.VaultEngine` in a
tight loop and appends one JSON line per **acknowledged** write to a progress
log *outside* the vault. Every line in that log is a write whose ``await``
returned, so the checker can assert the promise the engine makes: an
acknowledged write is on disk, intact, and committed.

Run directly with a Python interpreter — never through a wrapper. SPEC-003's
findings flag the trap: ``uv run script.py`` execs a *child* interpreter, so
killing the wrapper's PID leaves the real writer alive, racing the checker
and producing results that look like corruption but are not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from palaia_hub.vault import Attribution, GitPolicy, VaultEngine

ATTRIBUTION = Attribution(agent="kill-test", client="pytest", provider="local")


async def burst(vault_dir: Path, progress_path: Path, count: int) -> None:
    engine = VaultEngine(
        vault_dir,
        "killtest",
        policy=GitPolicy(gc_auto=256, gc_detach=False, gc_commit_interval=0, stale_lock_after=0.25),
    )
    await engine.open(purpose="kill -9 durability harness")
    with progress_path.open("a", encoding="utf-8") as progress:
        for index in range(count):
            result = await engine.write_note(
                f"notes/note-{index:05d}",
                title=f"Note {index}",
                body=f"- [index] {index}\n- relates_to [[Note {max(index - 1, 0)}]]\n",
                attribution=ATTRIBUTION,
                summary=f"write note {index}",
            )
            assert result.note is not None
            progress.write(
                json.dumps(
                    {
                        "path": result.note.path,
                        "permalink": result.note.permalink,
                        "checksum": result.note.checksum,
                        "commit": result.commit,
                    }
                )
                + "\n"
            )
            progress.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--progress", required=True)
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args()
    asyncio.run(burst(Path(args.vault_dir), Path(args.progress), args.count))


if __name__ == "__main__":
    main()
