"""MCP write-burst worker for the S3 kill/recover scenario (SPEC-113).

Same pattern as SPEC-102's ``tests/vault/support/write_burst.py``, one layer
up the stack: instead of writing through the engine directly, this writes
through the *running hub's* gateway over real streamable HTTP, so the kill
test exercises the whole process, not just the engine. Every acknowledged
tool call (the ``await`` for ``call_tool`` returned, non-error) is logged as
one JSON line to a progress file outside the vault — exactly the promise
the checker verifies afterwards: an acknowledged write is on disk, intact,
and (once the hub is healthy again) readable through the gateway.

Run directly with a Python interpreter — never through a wrapper — so
killing this process's PID kills the real writer (see
``support/hub_server.py``'s docstring for why that matters).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # for `simulator`

from simulator import SimulatedClient  # noqa: E402 - path insert must come first


async def burst(url: str, progress_path: Path, count: int) -> None:
    async with SimulatedClient(url, client_name="s3-write-burst") as client:
        with progress_path.open("a", encoding="utf-8") as progress:
            for index in range(count):
                try:
                    result = await client.call_tool(
                        "work_memory_write",
                        {
                            "title": f"Kill Test Note {index:05d}",
                            "body": f"- [index] {index}",
                            "folder": "killtest",
                        },
                    )
                except Exception:  # noqa: BLE001 - the hub may already be dead
                    break
                if result.is_error:
                    # The hub may already be gone by the time this call
                    # lands — that write was never acknowledged, so it is
                    # correctly absent from the progress log.
                    break
                assert result.structured is not None
                progress.write(
                    json.dumps(
                        {
                            "index": index,
                            "permalink": result.structured["permalink"],
                            "title": result.structured["title"],
                        }
                    )
                    + "\n"
                )
                progress.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--progress", required=True)
    parser.add_argument("--count", type=int, default=10_000)
    args = parser.parse_args()
    asyncio.run(burst(args.url, Path(args.progress), args.count))


if __name__ == "__main__":
    main()
