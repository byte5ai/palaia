"""SPEC-107 acceptance tests: the ``capture``/``inbox_status`` tools built
into each vault's memory tool family, exercised through
:class:`~palaia_hub.gateway.fake_vault.FakeVaultService`.
"""

from __future__ import annotations

import re

import pytest
from fastmcp import Client

from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server

_CAPTURE_ID_RE = re.compile(r"^cap-[0-9a-f]{10}$")


@pytest.fixture
def vault_config() -> VaultMountConfig:
    return VaultMountConfig(key="work", name="work", purpose="Team knowledge.")


@pytest.fixture
def service() -> FakeVaultService:
    return FakeVaultService()


@pytest.fixture
def server(vault_config: VaultMountConfig, service: FakeVaultService):  # noqa: ANN201
    return build_vault_server(vault_config, service)


async def _capture(client: Client, **overrides: str) -> object:  # noqa: ANN401
    payload = {
        "what_it_concerns": "API Gateway",
        "why_keep": "The rate limit was chosen deliberately; future work will trip over it.",
        "content": "We capped ingest at 100 req/min because the embed queue saturates above that.",
    }
    payload.update(overrides)
    return await client.call_tool("capture", payload)


@pytest.mark.anyio
async def test_capture_with_only_mandatory_fields_succeeds(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await _capture(client)
    assert result.is_error is not True
    sc = result.structured_content
    assert sc["permalink"].startswith("inbox/")
    assert sc["status"] == "uncurated"
    assert _CAPTURE_ID_RE.match(sc["capture_id"])
    assert sc["duplicate"] is False


@pytest.mark.anyio
async def test_capture_missing_mandatory_field_names_it_with_an_example(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool(
            "capture",
            {"what_it_concerns": "API Gateway", "content": "some raw detail"},
            raise_on_error=False,
        )
    assert result.is_error is True
    text = result.content[0].text
    assert "why_keep" in text
    assert "Example:" in text


@pytest.mark.anyio
async def test_capture_missing_all_mandatory_fields_names_all_of_them(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool("capture", {}, raise_on_error=False)
    assert result.is_error is True
    text = result.content[0].text
    for field in ("what_it_concerns", "why_keep", "content"):
        assert field in text


@pytest.mark.anyio
async def test_exact_duplicate_capture_is_acked_not_duplicated(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        first = await _capture(client)
        second = await _capture(client)

        listing = await client.call_tool("list", {"folder": "inbox"})

    assert first.structured_content["duplicate"] is False
    assert second.structured_content["duplicate"] is True
    assert second.structured_content["permalink"] == first.structured_content["permalink"]
    assert len(listing.structured_content["notes"]) == 1


@pytest.mark.anyio
async def test_near_duplicate_with_different_content_is_not_deduped(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await _capture(client)
        second = await _capture(client, content="a completely different observation")
        listing = await client.call_tool("list", {"folder": "inbox"})

    assert second.structured_content["duplicate"] is False
    assert len(listing.structured_content["notes"]) == 2


@pytest.mark.anyio
async def test_capture_id_is_deterministic_for_the_same_permalink(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await _capture(client)
    permalink = result.structured_content["permalink"]
    capture_id = result.structured_content["capture_id"]

    from palaia_hub.gateway.inbox import capture_id_for

    assert capture_id == capture_id_for(permalink)


@pytest.mark.anyio
async def test_captured_note_carries_entity_and_why_bullets_and_is_searchable(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        await _capture(client)
        read_result = await client.call_tool("read", {"permalink": "inbox/api-gateway"})
        search_result = await client.call_tool("search", {"query": "API Gateway"})

    body = read_result.structured_content["body"]
    assert "- [entity] API Gateway" in body
    assert "- [why] The rate limit was chosen deliberately" in body
    assert read_result.structured_content["status"] == "uncurated"
    assert any(
        hit["permalink"] == "inbox/api-gateway" for hit in search_result.structured_content["hits"]
    )


@pytest.mark.anyio
async def test_inbox_status_reports_zero_when_empty(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await client.call_tool("inbox_status", {})
    assert result.structured_content["count"] == 0
    assert result.structured_content["oldest_age_seconds"] is None


@pytest.mark.anyio
async def test_inbox_status_counts_captures_and_tracks_oldest_and_last(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        first = await _capture(client, what_it_concerns="First thing")
        await _capture(client, what_it_concerns="Second thing")
        status = await client.call_tool("inbox_status", {})

    sc = status.structured_content
    assert sc["count"] == 2
    assert sc["oldest_capture_id"] == first.structured_content["capture_id"]
    assert sc["oldest_age_seconds"] is not None
    assert sc["oldest_age_seconds"] >= 0
    assert sc["last_capture_id"] is not None


@pytest.mark.anyio
async def test_capture_default_source_when_omitted(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await _capture(client)
        read_result = await client.call_tool(
            "read", {"permalink": result.structured_content["permalink"]}
        )
    assert "- [source]" in read_result.structured_content["body"]


@pytest.mark.anyio
async def test_capture_uses_caller_supplied_source(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        result = await _capture(client, source="PR #88 review, cwendler, 2026-08-22")
        read_result = await client.call_tool(
            "read", {"permalink": result.structured_content["permalink"]}
        )
    body = read_result.structured_content["body"]
    assert "- [source] PR #88 review, cwendler, 2026-08-22" in body
