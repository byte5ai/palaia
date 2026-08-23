"""``recall`` / ``build_context`` as MCP tools: ergonomics and error shape.

SPEC-105's tool-ergonomics rules are not per-tool opinions — they are the
gateway's contract, so a new tool has to satisfy all of them: behavior
annotations, silent alias absorption, dual text+json output, the vault's
purpose leading the description, and caller-facing failures arriving as
``isError`` results rather than exceptions.

Two backings are exercised: the in-memory fake (fast, and what the golden
tool-schema snapshot is taken against) and a real engine+index behind
:class:`~palaia_hub.gateway.wiring.EngineVaultService` (the wiring a real hub
uses).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from recall_helpers import open_golden

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.gateway.vault_protocol import RECALL_TOOL_ACTIONS, NoteRecord
from palaia_hub.gateway.wiring import EngineVaultService

pytestmark = pytest.mark.anyio

VAULT = VaultMountConfig(key="work", name="work", purpose="Team knowledge for palaia.")


@pytest.fixture
def fake_service() -> FakeVaultService:
    service = FakeVaultService()
    service.seed(
        NoteRecord(
            permalink="glossary/base-rate",
            title="Base Rate",
            type="note",
            folder="glossary",
            body="- [rate-limit] 100 req/min ^rate-limit",
            modified="2026-08-20T00:00:00Z",
        )
    )
    service.seed(
        NoteRecord(
            permalink="glossary/pricing",
            title="Pricing",
            type="note",
            folder="glossary",
            body="Current pricing embeds the shared rate.\n\n![[Base Rate#^rate-limit]]",
            modified="2026-08-21T00:00:00Z",
        )
    )
    service.seed(
        NoteRecord(
            permalink="rules/commit-messages",
            title="Commit Messages",
            type="rule",
            folder="rules",
            body=(
                "- [how-to-apply] Prefer the compact form.\n"
                "- [how-to-apply | openai] Use imperative phrasing.\n"
                "- relates_to [[Pricing]]\n"
            ),
            modified="2026-08-22T00:00:00Z",
        )
    )
    return service


@pytest.fixture
async def fake_client(fake_service: FakeVaultService) -> AsyncIterator[Client[Any]]:
    server = build_vault_server(VAULT, fake_service)
    async with Client(server) as client:
        yield client


@pytest.fixture
async def real_client(tmp_path: Path) -> AsyncIterator[Client[Any]]:
    engine, index = await open_golden(tmp_path, "work")
    try:
        server = build_vault_server(VAULT, EngineVaultService(engine, index))
        async with Client(server) as client:
            yield client
    finally:
        await index.close()
        await engine.close()


# --------------------------------------------------------------------------
# Tool surface
# --------------------------------------------------------------------------

async def test_both_recall_tools_are_exposed(fake_client: Client[Any]) -> None:
    names = {tool.name for tool in await fake_client.list_tools()}
    assert set(RECALL_TOOL_ACTIONS) <= names


async def test_both_tools_are_annotated_read_only(fake_client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await fake_client.list_tools()}
    for name in RECALL_TOOL_ACTIONS:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is True


async def test_descriptions_lead_with_the_vaults_purpose(fake_client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await fake_client.list_tools()}
    for name in RECALL_TOOL_ACTIONS:
        assert tools[name].description is not None
        assert tools[name].description.startswith(VAULT.purpose)


async def test_the_published_schema_shows_only_canonical_parameter_names(
    fake_client: Client[Any],
) -> None:
    tools = {tool.name: tool for tool in await fake_client.list_tools()}
    for name in RECALL_TOOL_ACTIONS:
        properties = set(tools[name].inputSchema["properties"])
        assert "ref" in properties
        # The absorbed aliases stay out of the schema: an agent reading it
        # sees one name per concept.
        assert properties.isdisjoint({"permalink", "memory", "uri", "url", "q", "text"})


async def test_every_parameter_is_documented(fake_client: Client[Any]) -> None:
    tools = {tool.name: tool for tool in await fake_client.list_tools()}
    for name in RECALL_TOOL_ACTIONS:
        for parameter, schema in tools[name].inputSchema["properties"].items():
            assert schema.get("description"), f"{name}.{parameter} has no description"


async def test_the_assistant_guide_mentions_both_tools(fake_client: Client[Any]) -> None:
    resources = await fake_client.list_resources()
    guide_uri = next(str(r.uri) for r in resources if r.name == "ai_assistant_guide")
    contents = await fake_client.read_resource(guide_uri)
    text = "".join(getattr(block, "text", "") for block in contents)
    assert "recall" in text and "build_context" in text


# --------------------------------------------------------------------------
# Alias absorption
# --------------------------------------------------------------------------

@pytest.mark.parametrize("alias", ["ref", "permalink", "memory", "uri", "url"])
async def test_recall_absorbs_every_ref_alias(fake_client: Client[Any], alias: str) -> None:
    result = await fake_client.call_tool("recall", {alias: "glossary/pricing"})
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["entries"][0]["permalink"] == "glossary/pricing"


@pytest.mark.parametrize("alias", ["query", "q", "text"])
async def test_recall_absorbs_every_query_alias(fake_client: Client[Any], alias: str) -> None:
    result = await fake_client.call_tool("recall", {alias: "pricing"})
    assert not result.is_error, result.content


@pytest.mark.parametrize("alias", ["model", "model_id", "provider"])
async def test_recall_absorbs_every_model_alias(fake_client: Client[Any], alias: str) -> None:
    result = await fake_client.call_tool(
        "recall", {"ref": "rules/commit-messages", alias: "openai"}
    )
    assert not result.is_error, result.content
    entry = result.structured_content["entries"][0]  # type: ignore[index]
    assert [obs["text"] for obs in entry["observations"]] == ["Use imperative phrasing."]


async def test_build_context_absorbs_the_ref_alias(fake_client: Client[Any]) -> None:
    result = await fake_client.call_tool("build_context", {"permalink": "glossary/pricing"})
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["seeds"] == ["glossary/pricing"]


# --------------------------------------------------------------------------
# Dual output
# --------------------------------------------------------------------------

async def test_recall_returns_text_and_structured_content_together(
    fake_client: Client[Any],
) -> None:
    result = await fake_client.call_tool("recall", {"ref": "glossary/pricing"})
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "Pricing" in text
    assert "100 req/min" in text, "the human-readable half must show resolved values"
    assert result.structured_content is not None
    assert result.structured_content["entries"][0]["title"] == "Pricing"


async def test_build_context_returns_text_and_structured_content_together(
    fake_client: Client[Any],
) -> None:
    result = await fake_client.call_tool(
        "build_context", {"ref": "rules/commit-messages", "depth": 1}
    )
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "Context for" in text
    assert result.structured_content is not None
    assert result.structured_content["nodes"]
    for node in result.structured_content["nodes"]:
        assert node["text"] in text


# --------------------------------------------------------------------------
# Error shape
# --------------------------------------------------------------------------

async def test_recall_with_no_starting_point_is_a_tool_error(
    fake_client: Client[Any],
) -> None:
    result = await fake_client.call_tool("recall", {}, raise_on_error=False)
    assert result.is_error
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "query" in text and "ref" in text


async def test_recall_of_an_unknown_ref_is_a_tool_error_not_an_exception(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool(
        "recall", {"ref": "no/such/note"}, raise_on_error=False
    )
    assert result.is_error
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "no/such/note" in text


async def test_an_ambiguous_ref_lists_the_candidates_as_a_tool_error(
    tmp_path: Path,
) -> None:
    from recall_helpers import open_vault

    root = tmp_path / "amb3"
    root.mkdir()
    engine, index = await open_vault(root, "work")
    try:
        await engine.write_note("a/dup.md", body="One.", title="Dup", frontmatter={"type": "note"})
        await engine.write_note("b/dup.md", body="Two.", title="Dup", frontmatter={"type": "note"})
        await index.reindex()
        server = build_vault_server(VAULT, EngineVaultService(engine, index))
        async with Client(server) as client:
            result = await client.call_tool("recall", {"ref": "Dup"}, raise_on_error=False)
        assert result.is_error
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "a/dup" in text and "b/dup" in text
    finally:
        await index.close()
        await engine.close()


async def test_recall_without_an_index_says_what_is_missing(tmp_path: Path) -> None:
    from palaia_hub.vault import VaultEngine

    engine = VaultEngine(tmp_path / "no-index", "work")
    await engine.open(purpose="no index")
    try:
        server = build_vault_server(VAULT, EngineVaultService(engine))
        async with Client(server) as client:
            result = await client.call_tool("recall", {"query": "x"}, raise_on_error=False)
        assert result.is_error
        text = "".join(getattr(block, "text", "") for block in result.content)
        assert "index" in text
    finally:
        await engine.close()


# --------------------------------------------------------------------------
# Against the real wiring
# --------------------------------------------------------------------------

async def test_recall_over_the_real_wiring_resolves_values_and_variants(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool(
        "recall", {"ref": "glossary/pricing-summary"}, raise_on_error=False
    )
    assert not result.is_error, result.content
    body = result.structured_content["entries"][0]["body"]  # type: ignore[index]
    assert "100 req/min" in body

    scoped = await real_client.call_tool(
        "recall", {"ref": "rules/how-to-write-commit-messages", "model": "anthropic/opus-5"}
    )
    observations = scoped.structured_content["entries"][0]["observations"]  # type: ignore[index]
    assert [obs["text"] for obs in observations] == [
        "Use the extended form with a one-paragraph rationale."
    ]


async def test_read_shows_resolved_values_but_keeps_the_raw_body(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool("read", {"permalink": "glossary/pricing"})
    text = "".join(getattr(block, "text", "") for block in result.content)
    assert "100 req/min" in text, "the text half must show the live value"
    structured = result.structured_content
    assert structured is not None
    assert "![[Base Rate#^rate-limit]]" in structured["body"], (
        "the structured half must keep the note as written"
    )
    assert "100 req/min" in structured["resolved_body"]


async def test_read_of_a_note_without_embeds_reports_no_resolved_body(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool("read", {"permalink": "projects/api-gateway"})
    structured = result.structured_content
    assert structured is not None
    assert structured["resolved_body"] == ""
    assert structured["resolution_warnings"] == []


async def test_build_context_over_the_real_wiring_walks_the_graph(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool(
        "build_context", {"ref": "projects/recall-engine", "depth": 2}
    )
    assert not result.is_error, result.content
    structured = result.structured_content
    assert structured is not None
    permalinks = {node["permalink"] for node in structured["nodes"]}
    assert {"projects/recall-engine", "projects/vault-engine"} <= permalinks
    assert structured["estimated_tokens"] <= structured["max_tokens"]


async def test_configured_weights_reach_the_tool_and_change_the_ranking(
    tmp_path: Path,
) -> None:
    """``config.yaml``'s ``recall:`` section is load-bearing, not decorative.

    The whole path is exercised: a config file on disk → ``HubConfig`` →
    ``weights_from_settings`` → ``EngineVaultService`` → the ``recall`` tool's
    reported factors.
    """
    from palaia_hub.config import load_config
    from palaia_hub.recall.ranking import weights_from_settings

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text(
        "recall:\n  recency_weight: 0\n  access_weight: 0\n  significance_weight: 0\n",
        encoding="utf-8",
    )
    config = load_config(home=home)
    assert config.recall.recency_weight == 0.0

    engine, index = await open_golden(tmp_path, "work")
    try:
        service = EngineVaultService(
            engine, index, ranking=weights_from_settings(config.recall)
        )
        server = build_vault_server(VAULT, service)
        async with Client(server) as client:
            result = await client.call_tool("recall", {"query": "files are truth", "limit": 2})
        entries = result.structured_content["entries"]  # type: ignore[index]
        # Every weight zeroed: decay contributes nothing, so the answer is the
        # retriever's own order — which for this query puts the more central
        # note second, not first (see the ranking battery's row for it).
        assert [entry["permalink"] for entry in entries] == [
            "decisions/files-are-truth",
            "projects/vault-engine",
        ]
        assert entries[0]["score"] > entries[1]["score"]
        # ...and the reported score is exactly the un-boosted reciprocal rank.
        from palaia_hub.recall.ranking import relevance_of

        assert entries[0]["score"] == pytest.approx(relevance_of(0))
    finally:
        await index.close()
        await engine.close()


async def test_build_context_honors_a_small_budget_through_the_tool(
    real_client: Client[Any],
) -> None:
    result = await real_client.call_tool(
        "build_context", {"ref": "projects/recall-engine", "depth": 3, "max_tokens": 150}
    )
    structured = result.structured_content
    assert structured is not None
    assert structured["nodes"], "a tight budget must still name something"
    assert structured["estimated_tokens"] <= structured["max_tokens"]
    assert structured["degraded"] is True
