"""The guard matrix: every forbidden call is refused at the gateway.

SPEC-206 acceptance criterion #1, table-driven. Two layers are asserted:

- the pure policy (:func:`palaia_hub.curator.policy.rejection_for`) — the
  table itself;
- the same table driven through a **real curator profile** over a real
  ``FastMCP`` client, so what is tested is what a session actually reaches:
  the middleware, mounted on the profile the gateway builder produced.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastmcp import Client

from palaia_hub.curator.policy import CURATOR_TOOL_ACTIONS, provenance_line, rejection_for
from palaia_hub.curator.profile import (
    CURATOR_PROFILE_PATH,
    allowed_tool_specs,
    curator_profile,
    curator_profile_middleware,
    curator_tool_actions,
)
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService

CAPTURE_ID = "cap-3f9a1c02d4"
PROVENANCE = provenance_line(CAPTURE_ID)
NOT_ON_SURFACE = "not part of the curator's tool surface"

#: ``(label, action, arguments, expected substring)`` — every row is a call
#: SPEC-206 rule 2 forbids, plus the reason it must be refused with.
FORBIDDEN: list[tuple[str, str, dict[str, Any], str]] = [
    (
        "move is not on the surface",
        "move",
        {"permalink": "projects/x", "folder": "archive"},
        NOT_ON_SURFACE,
    ),
    ("delete is not on the surface", "delete", {"permalink": "projects/x"}, NOT_ON_SURFACE),
    ("capture is not on the surface", "capture", {"what_it_concerns": "x"}, NOT_ON_SURFACE),
    ("recall is not on the surface", "recall", {"query": "x"}, NOT_ON_SURFACE),
    (
        "edit replacing the body",
        "edit",
        {"permalink": "projects/api-gateway", "body": f"rewritten\n{PROVENANCE}"},
        "MAINTENANCE",
    ),
    (
        "edit with neither append nor body",
        "edit",
        {"permalink": "projects/api-gateway", "tags": ["infra"]},
        "append",
    ),
    (
        "edit of an existing review/ proposal",
        "edit",
        {"permalink": "review/merge-rate-limits", "append": f"- [note] ok\n{PROVENANCE}"},
        "never edit existing ones",
    ),
    (
        "edit of an inbox capture",
        "edit",
        {"permalink": "inbox/rate-limit", "append": f"- [note] ok\n{PROVENANCE}"},
        "never edits inbox/",
    ),
    (
        "write into inbox/",
        "write",
        {"title": "Rate limit", "body": PROVENANCE, "folder": "inbox"},
        "never writes into inbox/",
    ),
    (
        "write into inbox/ via the folder alias",
        "write",
        {"title": "Rate limit", "body": PROVENANCE, "path": "inbox/2026"},
        "never writes into inbox/",
    ),
    (
        "write with overwrite semantics",
        "write",
        {"title": "Rate limit", "body": PROVENANCE, "overwrite": True},
        "create-only",
    ),
    (
        "write with must_create disabled",
        "write",
        {"title": "Rate limit", "body": PROVENANCE, "must_create": False},
        "create-only",
    ),
    (
        "write with mode=replace",
        "write",
        {"title": "Rate limit", "body": PROVENANCE, "mode": "replace"},
        "create-only",
    ),
    (
        "write with no provenance line",
        "write",
        {"title": "Rate limit", "body": "The limit is 100 req/min."},
        "provenance line",
    ),
    (
        "write citing another capture",
        "write",
        {"title": "Rate limit", "body": provenance_line("cap-0000000000")},
        "this session is curating",
    ),
    (
        "append with no provenance line",
        "edit",
        {"permalink": "projects/api-gateway", "append": "- [note] the limit is 100"},
        "provenance line",
    ),
]

#: Calls the policy must allow — the other half of a guard matrix.
ALLOWED: list[tuple[str, str, dict[str, Any]]] = [
    ("search", "search", {"query": "rate limit"}),
    ("read", "read", {"permalink": "projects/api-gateway"}),
    ("list", "list", {"folder": "projects"}),
    ("recent_activity", "recent_activity", {}),
    ("build_context", "build_context", {"ref": "projects/api-gateway"}),
    (
        "write a new note with provenance",
        "write",
        {"title": "Rate limit", "body": f"100 req/min.\n{PROVENANCE}", "folder": "projects"},
    ),
    (
        "write a new proposal into review/",
        "write",
        {"title": "Merge rate limits", "body": f"...\n{PROVENANCE}", "folder": "review"},
    ),
    (
        "append observations with provenance",
        "edit",
        {"permalink": "projects/api-gateway", "append": f"- [limit] 100\n{PROVENANCE}"},
    ),
]


@pytest.mark.parametrize(
    ("label", "action", "arguments", "expected"),
    FORBIDDEN,
    ids=[row[0] for row in FORBIDDEN],
)
def test_policy_refuses_every_forbidden_call(
    label: str, action: str, arguments: dict[str, Any], expected: str
) -> None:
    message = rejection_for(action, arguments, expected_captures={CAPTURE_ID})
    assert message is not None, f"{label} must be refused"
    assert expected in message
    # Every refusal says what to do instead (SPEC-206's prompt: "a rejected
    # call is information, not an obstacle").
    assert message.startswith("rejected: ")
    assert len(message) > 80


@pytest.mark.parametrize(
    ("label", "action", "arguments"), ALLOWED, ids=[row[0] for row in ALLOWED]
)
def test_policy_allows_the_curator_surface(
    label: str, action: str, arguments: dict[str, Any]
) -> None:
    assert rejection_for(action, arguments, expected_captures={CAPTURE_ID}) is None


def test_provenance_is_shape_checked_when_no_session_is_registered() -> None:
    """No active capture (an out-of-process session) still requires provenance."""
    assert rejection_for("write", {"title": "x", "body": "no provenance"}) is not None
    assert rejection_for("write", {"title": "x", "body": provenance_line("cap-abc")}) is None


# --- the same matrix, through a real profile -------------------------------


def _curator_gateway(mount: VaultMountConfig) -> Any:
    config = GatewayConfig(vaults=[mount], profiles=[curator_profile([mount.key])])
    middleware = curator_profile_middleware([mount])
    gateway = build_gateway(
        config, {mount.key: FakeVaultService()}, profile_middleware=middleware
    )
    return gateway, middleware[CURATOR_PROFILE_PATH][0]


@pytest.mark.anyio
async def test_curator_profile_lists_only_the_allowed_tools(
    vault_mount: VaultMountConfig,
) -> None:
    gateway, _middleware = _curator_gateway(vault_mount)
    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        names = {tool.name for tool in await client.list_tools()}
    expected = {
        name
        for name, action in curator_tool_actions([vault_mount]).items()
        if action in CURATOR_TOOL_ACTIONS
    }
    assert names == expected
    # The forbidden half is genuinely absent, not merely unadvertised.
    assert f"{vault_mount.namespace}_delete" not in names
    assert f"{vault_mount.namespace}_capture" not in names


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("label", "action", "arguments", "expected"),
    FORBIDDEN,
    ids=[row[0] for row in FORBIDDEN],
)
async def test_gateway_refuses_every_forbidden_call(
    vault_mount: VaultMountConfig,
    label: str,
    action: str,
    arguments: dict[str, Any],
    expected: str,
) -> None:
    gateway, middleware = _curator_gateway(vault_mount)
    middleware.active_captures.acquire(CAPTURE_ID)
    tool = f"{vault_mount.namespace}_{action}"
    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error, f"{label} reached the vault"
    assert expected in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_allowed_write_reaches_the_vault(vault_mount: VaultMountConfig) -> None:
    gateway, middleware = _curator_gateway(vault_mount)
    middleware.active_captures.acquire(CAPTURE_ID)
    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        result = await client.call_tool(
            f"{vault_mount.namespace}_write",
            {
                "title": "Ingest rate limit",
                "body": f"100 req/min.\n{PROVENANCE}",
                "folder": "projects",
            },
            raise_on_error=False,
        )
    assert not result.is_error
    assert "created" in result.content[0].text  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_a_released_session_loses_its_capture_binding(
    vault_mount: VaultMountConfig,
) -> None:
    """The binding lives exactly as long as the session it was acquired for."""
    gateway, middleware = _curator_gateway(vault_mount)
    middleware.active_captures.acquire(CAPTURE_ID)
    assert middleware.active_captures.current() == {CAPTURE_ID}
    middleware.active_captures.release(CAPTURE_ID)
    assert middleware.active_captures.current() == frozenset()
    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        result = await client.call_tool(
            f"{vault_mount.namespace}_write",
            {"title": "Whatever", "body": provenance_line("cap-somethingelse")},
            raise_on_error=False,
        )
    # Shape-only checking: any well-formed provenance passes once no session
    # is registered (documented fallback, see ActiveCaptures).
    assert not result.is_error


def test_allowed_tool_specs_match_the_narrowed_surface(
    vault_mount: VaultMountConfig,
) -> None:
    specs = allowed_tool_specs([vault_mount])
    assert len(specs) == len(CURATOR_TOOL_ACTIONS)
    assert f"mcp__palaia__{vault_mount.namespace}_write" in specs
    assert all(spec.startswith("mcp__palaia__") for spec in specs)
    assert not any(spec.endswith("_delete") for spec in specs)


def test_renamed_tools_are_still_classified_by_their_action() -> None:
    """A vault that renames ``write`` does not thereby escape the guard."""
    mount = VaultMountConfig(key="work", name="work", tool_renames={"write": "remember"})
    mapping = curator_tool_actions([mount])
    assert mapping[f"{mount.namespace}_remember"] == "write"
    assert f"{mount.namespace}_write" not in mapping
