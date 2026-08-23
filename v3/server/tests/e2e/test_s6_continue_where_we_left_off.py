"""S6 "continue where we left off" (SPEC-106's last acceptance criterion).

The scenario the whole memory system exists for, end to end and un-faked: a
simulated Claude Code session records where it stopped, the session ends, and
a *fresh* session with no memory of the first one asks the vault to bring it
back up to speed. What comes back must be the seeded state plus the notes it
relates to — assembled by walking the graph, not by re-searching.

Everything below is real: a live hub subprocess over the golden vault's
``work`` copy, the real gateway, real streamable HTTP, the real vault engine,
the real index (FTS-only — embeddings are off in ``hub_server.py``, so this
also exercises the degraded-retrieval path), and the real recall layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from simulator import SimulatedClient

if TYPE_CHECKING:
    from conftest import HubFactory

pytestmark = pytest.mark.anyio

#: What the first session leaves behind. Deliberately shaped like real
#: hand-off state: prose plus observations plus relations into notes that
#: already exist in the golden vault, which is what gives the walk somewhere
#: to go.
HANDOFF_TITLE = "Recall Engine Session Handoff"
HANDOFF_BODY = """\
Stopped mid-way through the traversal work.

- [next-step] Wire the token budget into the context assembler
- [open-question] Should the walk follow inbound relations by default
- part_of [[Recall Engine]]
- relates_to [[Vault Engine]]
"""


async def test_a_fresh_session_gets_the_previous_sessions_context_back(
    golden_work_vault: Path, hub_factory: HubFactory
) -> None:
    hub = hub_factory(vault_dir=golden_work_vault, profiles=["claude-code"])

    # --- session one: work happens, state is recorded, session ends --------
    async with SimulatedClient(
        hub.profile_url("claude-code"), client_name="claude-code", client_version="1.0.0"
    ) as first_session:
        written = await first_session.call_tool_ok(
            "work_memory_write",
            {"title": HANDOFF_TITLE, "body": HANDOFF_BODY, "folder": "projects"},
        )
        assert written.structured is not None
        handoff_permalink = written.structured["permalink"]

    # --- session two: no shared state, only the vault ----------------------
    async with SimulatedClient(
        hub.profile_url("claude-code"), client_name="claude-code", client_version="2.0.0"
    ) as next_session:
        result = await next_session.call_tool_ok(
            "work_memory_build_context",
            {"query": "where did we leave off on the recall engine", "depth": 2},
        )

        # The seeded hand-off note is what the query found...
        assert handoff_permalink in result.structured["seeds"], (
            f"the hand-off note did not seed the context: {result.structured['seeds']}"
        )

        permalinks = {node["permalink"] for node in result.structured["nodes"]}
        # ...and the walk brought its neighborhood with it, without the
        # caller ever naming those notes.
        assert handoff_permalink in permalinks
        assert "projects/recall-engine" in permalinks, permalinks
        assert "projects/vault-engine" in permalinks, permalinks

        # The human-readable half carries the actual state, not just names.
        assert "Wire the token budget into the context assembler" in result.text
        assert "Should the walk follow inbound relations by default" in result.text

        # Every non-seed node says which relation reached it — the hand-off
        # is auditable, not a bag of notes.
        for node in result.structured["nodes"]:
            if node["depth"] > 0:
                assert node["via"], f"{node['permalink']} arrived without an edge label"
                assert node["parent"]

        # The package stayed inside its budget and reports it.
        assert result.structured["estimated_tokens"] <= result.structured["max_tokens"]


async def test_the_same_hand_off_is_reachable_by_reference_and_by_recall(
    golden_work_vault: Path, hub_factory: HubFactory
) -> None:
    hub = hub_factory(vault_dir=golden_work_vault, profiles=["claude-code"])

    async with SimulatedClient(
        hub.profile_url("claude-code"), client_name="claude-code"
    ) as session:
        written = await session.call_tool_ok(
            "work_memory_write",
            {"title": HANDOFF_TITLE, "body": HANDOFF_BODY, "folder": "projects"},
        )
        assert written.structured is not None
        permalink = written.structured["permalink"]

        # By reference: memory:// addressing over the wire.
        by_ref = await session.call_tool_ok(
            "work_memory_recall", {"ref": f"memory://{permalink}"}
        )
        assert by_ref.structured["entries"][0]["permalink"] == permalink
        categories = {
            obs["category"] for obs in by_ref.structured["entries"][0]["observations"]
        }
        assert {"next-step", "open-question"} <= categories

        # By reference, one hop out: build_context from the note itself.
        by_context = await session.call_tool_ok(
            "work_memory_build_context", {"ref": permalink, "depth": 1}
        )
        assert by_context.structured["seeds"] == [permalink]
        assert len(by_context.structured["nodes"]) > 1


async def test_recall_over_the_wire_resolves_shared_values_and_model_variants(
    golden_work_vault: Path, hub_factory: HubFactory
) -> None:
    """The two resolution features, asserted through the real MCP endpoint."""
    hub = hub_factory(vault_dir=golden_work_vault, profiles=["claude-code"])

    async with SimulatedClient(
        hub.profile_url("claude-code"), client_name="claude-code"
    ) as session:
        # A value reference resolves to the current source value.
        pricing = await session.call_tool_ok(
            "work_memory_recall", {"ref": "glossary/pricing-summary"}
        )
        assert "100 req/min" in pricing.structured["entries"][0]["body"]

        # A per-model variant group serves exactly one line per caller.
        for model, expected in (
            ("anthropic/opus-5", "Use the extended form with a one-paragraph rationale."),
            ("openai", "Use imperative phrasing throughout."),
            ("", "Prefer the compact form: subject line only."),
        ):
            result = await session.call_tool_ok(
                "work_memory_recall",
                {"ref": "rules/how-to-write-commit-messages", "model": model},
            )
            served = [
                obs["text"] for obs in result.structured["entries"][0]["observations"]
            ]
            assert served == [expected], f"model {model!r} was served {served}"
