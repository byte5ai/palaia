"""Smart Nudges on the MCP tool surface (issue #301).

Two layers are covered here. First the adapter in
:mod:`palaia_hub.gateway.guidance` — that a tool result's own fields become
the deterministic signal record, without the adapter reading anything extra.
Then the thing that actually matters: an MCP client calling a real built
vault server gets the guidance in the output it reads, on both halves of the
dual text/json result, and gets nothing at all on an ordinary call.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.guidance import (
    GUIDANCE_HEADING,
    current_session_key,
    nudged_result,
    signals_for,
)
from palaia_hub.gateway.memory_tools import DeleteResult, SearchResult, build_vault_server
from palaia_hub.gateway.vault_protocol import (
    CaptureResult,
    InboxStatusResult,
    NoteRecord,
    SearchHit,
)
from palaia_hub.nudges import ANONYMOUS_SESSION, Nudge, NudgeEngine, VaultSignals
from palaia_hub.recall.models import ContextResult, RecallEntry, RecallResult


@pytest.fixture
def vault_config() -> VaultMountConfig:
    return VaultMountConfig(key="work", name="work", purpose="Team knowledge.")


# --- the result -> signals adapter ------------------------------------------


def test_a_degraded_recall_result_carries_its_reason_into_the_signals() -> None:
    result = RecallResult(
        query="rate limits",
        entries=[RecallEntry(ref="a", permalink="a", title="A")],
        degraded=True,
        degraded_reason="no vectors are ready yet",
    )
    signals = signals_for("recall", result, vault_key="work")
    assert signals.action == "recall"
    assert signals.vault_key == "work"
    assert signals.hits == 1
    assert signals.degraded
    assert signals.degraded_reason == "no vectors are ready yet"


def test_a_context_result_reports_what_the_budget_left_out() -> None:
    result = ContextResult(degraded=True, dropped=["ops/a", "ops/b"])
    signals = signals_for("build_context", result)
    assert signals.dropped_notes == 2
    assert signals.degraded


def test_a_duplicate_capture_result_carries_the_existing_permalink() -> None:
    result = CaptureResult(
        permalink="inbox/rate-limit", title="Rate limit", capture_id="cap-1", duplicate=True
    )
    signals = signals_for("capture", result)
    assert signals.duplicate_capture
    assert signals.duplicate_permalink == "inbox/rate-limit"


def test_an_inbox_status_result_carries_its_count() -> None:
    assert signals_for("inbox_status", InboxStatusResult(count=12)).inbox_count == 12


def test_a_note_record_carries_its_resolution_warnings() -> None:
    note = NoteRecord(
        permalink="ops/limits",
        title="Limits",
        resolution_warnings=["embed-missing: ops/rate#value"],
    )
    signals = signals_for("read", note)
    assert signals.unresolved_values == ("embed-missing: ops/rate#value",)


def test_a_search_result_is_matched_structurally_by_its_hit_list() -> None:
    """``SearchResult`` cannot be imported by the adapter without a cycle —
    see :func:`palaia_hub.gateway.guidance.signals_for`."""
    empty = signals_for("search", SearchResult(query="nothing", hits=[]))
    one = signals_for("search", SearchResult(query="x", hits=[SearchHit(permalink="a", title="A")]))
    assert empty.hits == 0
    assert one.hits == 1


def test_a_result_with_no_signal_still_produces_a_record() -> None:
    """Every tool routes through the same helper; results that carry nothing
    simply fire nothing."""
    signals = signals_for("delete", DeleteResult(permalink="a", deleted=True))
    assert signals.action == "delete"
    assert signals.hits is None
    assert not signals.degraded


def test_the_session_key_falls_back_outside_a_served_request() -> None:
    """Called here with no FastMCP context at all, which is exactly what a
    direct in-process call looks like."""
    assert current_session_key() == ANONYMOUS_SESSION


# --- injection into the tool result -----------------------------------------


def always_nudge(_: VaultSignals) -> Nudge:
    return Nudge(key="test.always", text="Something is off. Fix: do the thing.")


def test_guidance_lands_on_both_halves_of_the_result() -> None:
    engine = NudgeEngine(detectors=(always_nudge,))
    result = nudged_result(
        engine,
        action="search",
        text="2 match(es)",
        payload=SearchResult(query="x", hits=[]),
    )
    text = result.content[0].text  # type: ignore[union-attr]
    assert text.startswith("2 match(es)")
    assert GUIDANCE_HEADING in text
    assert "Fix: do the thing." in text
    assert result.structured_content is not None
    assert result.structured_content["guidance"] == ["Something is off. Fix: do the thing."]
    # The payload itself is untouched — guidance rides along, it does not
    # replace or reshape what the tool answered.
    assert result.structured_content["query"] == "x"
    json.dumps(result.structured_content)


def test_a_result_with_no_guidance_is_unchanged() -> None:
    """The common case. No `guidance` key at all rather than an empty list:
    an always-present empty field is a per-call cost for no information."""
    engine = NudgeEngine(detectors=())
    result = nudged_result(
        engine, action="search", text="2 match(es)", payload=SearchResult(query="x", hits=[])
    )
    assert result.content[0].text == "2 match(es)"  # type: ignore[union-attr]
    assert result.structured_content is not None
    assert "guidance" not in result.structured_content


# --- end to end through a real vault server ---------------------------------


@pytest.mark.anyio
async def test_an_empty_search_tells_the_agent_to_try_recall(
    vault_config: VaultMountConfig,
) -> None:
    server = build_vault_server(vault_config, FakeVaultService())
    async with Client(server) as client:
        result = await client.call_tool("search", {"query": "nothing-matches-this"})
    text = result.content[0].text  # type: ignore[union-attr]
    assert GUIDANCE_HEADING in text
    assert "recall" in text
    assert result.structured_content is not None
    assert any("recall" in line for line in result.structured_content["guidance"])


@pytest.mark.anyio
async def test_an_ordinary_search_carries_no_guidance(
    vault_config: VaultMountConfig,
) -> None:
    service = FakeVaultService()
    await service.write("Rate limits", "We capped ingest at 100 req/min.")
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool("search", {"query": "rate limits"})
    assert GUIDANCE_HEADING not in result.content[0].text  # type: ignore[union-attr]
    assert result.structured_content is not None
    assert "guidance" not in result.structured_content


@pytest.mark.anyio
async def test_a_deduplicated_capture_names_the_note_to_edit_instead(
    vault_config: VaultMountConfig,
) -> None:
    server = build_vault_server(vault_config, FakeVaultService())
    call = {
        "what_it_concerns": "API Gateway",
        "why_keep": "The rate limit was chosen deliberately.",
        "content": "Ingest is capped at 100 req/min because the embed queue saturates above that.",
    }
    async with Client(server) as client:
        first = await client.call_tool("capture", call)
        second = await client.call_tool("capture", call)
    assert first.structured_content is not None
    assert "guidance" not in first.structured_content, "a fresh capture earns nothing"
    assert second.structured_content is not None
    guidance = second.structured_content["guidance"]
    assert any("inbox/" in line for line in guidance)


@pytest.mark.anyio
async def test_the_same_nudge_does_not_repeat_within_one_session(
    vault_config: VaultMountConfig,
) -> None:
    """The rate policy, proven where it matters: over the wire, on the same
    connection, calling the same failing thing twice."""
    server = build_vault_server(vault_config, FakeVaultService())
    async with Client(server) as client:
        first = await client.call_tool("search", {"query": "nothing-matches-this"})
        second = await client.call_tool("search", {"query": "also-nothing-here"})
    assert first.structured_content is not None
    assert "guidance" in first.structured_content
    assert second.structured_content is not None
    assert "guidance" not in second.structured_content


@pytest.mark.anyio
async def test_an_error_result_carries_no_guidance(vault_config: VaultMountConfig) -> None:
    """An error already names its own fix; a second, unrelated instruction
    stapled to it is noise at the worst moment."""
    engine = NudgeEngine(detectors=(always_nudge,))
    server = build_vault_server(vault_config, FakeVaultService(), nudges=engine)
    async with Client(server) as client:
        result = await client.call_tool(
            "read", {"permalink": "does/not/exist"}, raise_on_error=False
        )
    assert result.is_error is True
    assert GUIDANCE_HEADING not in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_an_injected_engine_is_the_one_the_tools_use(
    vault_config: VaultMountConfig,
) -> None:
    """The seam the rest of this file relies on, asserted directly."""
    engine = NudgeEngine(detectors=(always_nudge,))
    server = build_vault_server(vault_config, FakeVaultService(), nudges=engine)
    async with Client(server) as client:
        result = await client.call_tool("list", {})
    assert result.structured_content is not None
    assert result.structured_content["guidance"] == ["Something is off. Fix: do the thing."]
