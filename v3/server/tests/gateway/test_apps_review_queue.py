"""Review-queue MCP App acceptance tests (SPEC-208 deliverable #4).

The "call it back" tests below build a real, *mounted* gateway profile via
:func:`~palaia_hub.gateway.build.build_gateway` (this codebase's own
production assembly path — not the bare, un-namespaced
:func:`~palaia_hub.gateway.memory_tools.build_vault_server` output some of
the other tests here use) and drive it in-memory through
:class:`fastmcp.Client`. That distinction matters for this SPEC
specifically: ``review_queue``'s ``decide_tool`` field names the tool's
*mounted, namespace-prefixed* wire name (see
``vault_protocol.ReviewQueueResult``'s docstring for why), so only a test
against a real mount actually proves that name is callable — calling it
against the bare, unmounted server would call a tool that does not exist
under that name there.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.gateway.vault_protocol import NoteRecord, VaultService, VaultServiceError
from palaia_hub.vault import VaultRegistry


@pytest.fixture
def vault_config() -> VaultMountConfig:
    return VaultMountConfig(key="work", name="work", purpose="Team knowledge.")


@pytest.fixture
def service() -> FakeVaultService:
    svc = FakeVaultService()
    svc.seed(
        NoteRecord(
            permalink="review/rate-limit-cleanup",
            title="Fold duplicate rate-limit notes",
            type="proposal",
            folder="review",
            status="proposed",
            created="2026-08-01T00:00:00Z",
            body="Two notes both describe the ingest rate limit; merge them.\n",
        )
    )
    return svc


def _mounted_profile(vault_config: VaultMountConfig, service: VaultService) -> FastMCP:
    """A real, namespace-mounted profile server for exactly one vault —
    the shape ``build.py`` produces in production, as opposed to the bare
    per-vault server :func:`build_vault_server` returns on its own."""
    config = GatewayConfig(
        vaults=[vault_config], profiles=[ProfileConfig(path="default", vaults=[vault_config.key])]
    )
    gateway = build_gateway(config, {vault_config.key: service})
    return gateway.profile_servers["default"]


@pytest.mark.anyio
async def test_review_queue_lists_pending_proposals_with_decide_tool(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool("review_queue", {})
    payload = result.structured_content
    assert payload is not None
    assert len(payload["proposals"]) == 1
    proposal = payload["proposals"][0]
    assert proposal["status"] == "proposed"
    assert proposal["permalink"] == "review/rate-limit-cleanup"
    assert payload["decide_tool"] == "work_memory_review_decide"
    # Plain-text fallback (deliverable #5): a host without the MCP Apps
    # extension still gets something useful from `content`.
    assert "1 proposal" in result.content[0].text


@pytest.mark.anyio
async def test_approve_from_the_app_flips_status(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = _mounted_profile(vault_config, service)
    async with Client(server) as client:
        queue = await client.call_tool("work_memory_review_queue", {})
        decide_tool = queue.structured_content["decide_tool"]
        assert decide_tool == "work_memory_review_decide"
        decision = await client.call_tool(
            decide_tool, {"permalink": "review/rate-limit-cleanup", "decision": "approved"}
        )
    assert decision.structured_content == {
        "permalink": "review/rate-limit-cleanup",
        "status": "approved",
    }
    updated = await service.read("review/rate-limit-cleanup")
    assert updated.status == "approved"


@pytest.mark.anyio
async def test_reject_from_the_app_flips_status(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    server = _mounted_profile(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool(
            "work_memory_review_decide",
            {"permalink": "review/rate-limit-cleanup", "decision": "rejected"},
        )
    assert result.structured_content["status"] == "rejected"


@pytest.mark.anyio
async def test_deciding_twice_is_refused(
    vault_config: VaultMountConfig, service: FakeVaultService
) -> None:
    await service.review_decide("review/rate-limit-cleanup", "approved")
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool(
            "review_decide",
            {"permalink": "review/rate-limit-cleanup", "decision": "rejected"},
            raise_on_error=False,
        )
    assert result.is_error
    assert "not awaiting review" in result.content[0].text


@pytest.mark.anyio
async def test_review_decide_on_a_non_proposal_note_is_refused(
    vault_config: VaultMountConfig,
) -> None:
    service = FakeVaultService()
    await service.write("Just a note", "nothing to review here")
    server = build_vault_server(vault_config, service)
    async with Client(server) as client:
        result = await client.call_tool(
            "review_decide",
            {"permalink": "just-a-note", "decision": "approved"},
            raise_on_error=False,
        )
    assert result.is_error
    assert "not a review proposal" in result.content[0].text


@pytest.mark.anyio
async def test_review_decide_on_the_service_directly_raises_for_unknown_permalink() -> None:
    """Sanity: :class:`FakeVaultService` actually implements the protocol
    method end to end, not just enough duck-typing to satisfy one call path
    routed through the tool layer above."""
    service = FakeVaultService()
    with pytest.raises(VaultServiceError):
        await service.review_decide("review/nope", "approved")


# --------------------------------------------------------------------------
# Dashboard REST parity: the review-queue app and the (future) dashboard
# screen both flip status through the identical VaultService call.
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dashboard_review_rest_endpoint_mirrors_the_app_decision(tmp_path) -> None:  # noqa: ANN001
    registry = VaultRegistry(tmp_path / "home")
    engine = await registry.create("work", tmp_path / "work")
    write_result = await engine.write_note(
        "review/dup.md",
        body="Two notes overlap.\n",
        title="Dedup two notes",
        frontmatter={"type": "proposal", "status": "proposed"},
        must_create=True,
    )
    assert write_result.note is not None
    permalink = write_result.note.permalink

    app = create_app(HubConfig(), vault_registry=registry)
    with TestClient(app) as rest:
        listed = rest.get("/api/vaults/work/review")
        assert listed.status_code == 200
        assert listed.json()["proposals"][0]["status"] == "proposed"

        decided = rest.post(
            f"/api/vaults/work/review/{permalink}/decision", json={"decision": "approved"}
        )
        assert decided.status_code == 200
        assert decided.json() == {"permalink": permalink, "status": "approved"}

        # The exact same effect an approve-from-the-app call would have had:
        note = await engine.read_note("review/dup.md")
        assert note.frontmatter["status"] == "approved"
