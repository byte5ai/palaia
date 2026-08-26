"""S2 "external edit: file edited on disk -> searchable within budget"
(SPEC-113).

A note is written straight to disk — bypassing the engine, exactly like a
human editing the file in Obsidian — while the real hub (with its
:class:`~palaia_hub.vault.VaultWatcher` running, per
``support/hub_server.py``) has the vault open. The budget is the watcher's
own documented one: a 200ms debounce plus the SPEC-003-measured ~2s
watchfiles observation budget (see ``palaia_hub/vault/watcher.py``'s module
docstring) — this test polls up to a generous multiple of that rather than
asserting an exact latency, since CI runners are not real-time systems.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio

_POLL_BUDGET_SECONDS = 10.0
_POLL_INTERVAL_SECONDS = 0.25


async def test_externally_written_note_becomes_searchable_within_budget(
    golden_work_vault: Path, hub_factory: HubFactory
) -> None:
    hub = hub_factory(vault_dir=golden_work_vault)

    external_note = golden_work_vault / "notes" / "written-by-an-external-editor.md"
    external_note.parent.mkdir(parents=True, exist_ok=True)
    external_note.write_text(
        "---\n"
        "title: Written By An External Editor\n"
        "permalink: notes/written-by-an-external-editor\n"
        "type: note\n"
        "---\n\n"
        "This note was written straight to disk, like an Obsidian save.\n",
        encoding="utf-8",
    )

    async with SimulatedClient(hub.profile_url(), client_name="poller") as client:
        deadline = asyncio.get_event_loop().time() + _POLL_BUDGET_SECONDS
        found = False
        while asyncio.get_event_loop().time() < deadline:
            result = await client.call_tool_ok(
                "work_memory_search", {"query": "external editor"}
            )
            if "Written By An External Editor" in result.text:
                found = True
                break
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    assert found, (
        f"externally written note was not searchable within "
        f"{_POLL_BUDGET_SECONDS}s (hub log: {hub.log_path})"
    )
