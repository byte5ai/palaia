"""S5 "fresh-install flow: container up -> wizard API -> first note"
(SPEC-113).

**Honest scope note:** the dashboard wizard and its HTTP config API are
SPEC-109/SPEC-110 — not merged as of this SPEC. There is no
"POST /api/wizard/vaults" or similar to drive yet. What this test exercises
is everything that IS real and merged today, wired exactly the way the
eventual wizard would have to wire it:

1. A completely empty directory (no vault, no ``.git``, no notes) —
   "container up" for someone who has never run palaia before.
2. The hub process starts and opens that directory as a brand-new vault
   (``VaultEngine.open(create=True)``, run inside ``support/hub_server.py``
   exactly like every other scenario here) — the same call a future wizard
   endpoint would make on "create my first vault", just not reachable over
   HTTP as a config API yet.
3. ``/api/health`` reports ready.
4. The first note goes in through the real gateway, over real streamable
   HTTP — the actual headline moment ("first note") the fresh-install story
   is about.

When SPEC-110 lands a real wizard API, this test is the natural place to
extend step 2 into an actual HTTP call instead of a fresh directory handed
straight to the hub.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio


async def test_fresh_install_creates_first_vault_and_takes_first_note(
    tmp_path: Path, hub_factory: HubFactory
) -> None:
    fresh_vault_dir = tmp_path / "brand-new-vault"
    assert not fresh_vault_dir.exists(), "this must start as a truly empty install"

    hub = hub_factory(vault_dir=fresh_vault_dir, vault_key="work", vault_name="work")

    # /api/health and /api/info are real, merged (SPEC-101) surfaces a
    # wizard's landing page would poll before offering "create your first
    # vault".
    with urllib.request.urlopen(f"http://127.0.0.1:{hub.port}/api/info", timeout=2) as resp:
        assert resp.status == 200

    # The vault now exists on disk, git-initialized, with its manifest —
    # VaultEngine.open(create=True) did the "wizard's" job.
    assert (fresh_vault_dir / ".git").is_dir()
    assert (fresh_vault_dir / "meta" / "vault.md").is_file()

    async with SimulatedClient(hub.profile_url(), client_name="fresh-install-check") as client:
        write_result = await client.call_tool_ok(
            "work_memory_write",
            {"title": "My First Note", "body": "the fresh-install headline moment"},
        )
        assert "My First Note" in write_result.text

        read_result = await client.call_tool_ok(
            "work_memory_read", {"permalink": "my-first-note"}
        )
        assert "the fresh-install headline moment" in read_result.text
