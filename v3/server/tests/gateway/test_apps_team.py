"""Session-monitor MCP App acceptance tests (SPEC-405 deliverable #3).

Same in-memory :class:`fastmcp.Client` pattern as
``test_apps_hub_status.py`` (see that file's own docstring for why no test
here drives a real HTTP streamable session).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.apps.team_app import (
    _SCRIPT_JS,
    TeamAppDeps,
    build_team_server,
    collect_team_monitor,
)
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore


def _deps(dashboard_url: str | None = None) -> TeamAppDeps:
    directory = DirectoryService(DirectoryStore(":memory:"))
    messenger = MessengerService(MessengerStore(":memory:"), directory)
    return TeamAppDeps(
        directory_service=directory, messenger_service=messenger, dashboard_url=dashboard_url
    )


@pytest.mark.anyio
async def test_collect_team_monitor_reports_sessions_and_flows() -> None:
    deps = _deps()
    a = await deps.directory_service.register(scope="reviewing billing", platform="claude-code")
    b = await deps.directory_service.register(scope="refactoring billing")
    await deps.messenger_service.send(
        sender=a.session.handle,
        session_secret=a.session_secret,
        message_type="inform",
        to=b.session.handle,
        subject="a note",
        body="the body a monitor app must never show",
    )

    result = await collect_team_monitor(deps)

    assert {s.handle for s in result.sessions} == {a.session.handle, b.session.handle}
    assert [f.subject for f in result.flows] == ["a note"]
    # Metadata only — no bodies on this surface (an MCP App is not the
    # owner's admin surface).
    assert not hasattr(result.flows[0], "body")


@pytest.mark.anyio
async def test_session_monitor_tool_carries_the_ui_resource_and_send_tool() -> None:
    deps = _deps(dashboard_url="https://hub.example.com")
    await deps.directory_service.register(scope="reviewing billing")
    server = build_team_server(deps)

    async with Client(server) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == {"session_monitor", "messenger_send"}
        (monitor_tool,) = [t for t in tools if t.name == "session_monitor"]
        assert monitor_tool.meta is not None
        assert monitor_tool.meta["ui"]["resourceUri"] == "ui://palaia/team.html"

        result = await client.call_tool("session_monitor", {})
        resources = await client.list_resources()

    assert {str(r.uri) for r in resources} == {"ui://palaia/team.html"}
    payload = result.structured_content
    assert len(payload["sessions"]) == 1
    assert payload["send_tool"] == "messenger_send"
    assert payload["dashboard_url"] == "https://hub.example.com"
    # Plain-text fallback (deliverable #3): a compact directory listing.
    assert "1 agent(s) registered" in result.content[0].text


@pytest.mark.anyio
async def test_messenger_send_on_the_team_server_actually_delivers() -> None:
    """The compose form's own tool, proven end to end: sending here lands
    in the real recipient's inbox — same as sending on ``/mcp/messenger``
    directly, because it is the same tool (see the module docstring)."""
    deps = _deps()
    a = await deps.directory_service.register(scope="composing")
    b = await deps.directory_service.register(scope="waiting")
    server = build_team_server(deps)

    async with Client(server) as client:
        result = await client.call_tool(
            "messenger_send",
            {
                "handle": a.session.handle,
                "session_secret": a.session_secret,
                "to": b.session.handle,
                "subject": "from the team app",
                "message_type": "inform",
            },
        )
    assert not result.is_error

    delivered = await deps.messenger_service.check(b.session.handle, b.session_secret)
    assert [e.subject for e in delivered.envelopes] == ["from the team app"]


def test_the_page_never_calls_a_server_tool_to_end_or_deregister() -> None:
    """The SPEC-304 rule this SPEC inherits: destructive owner controls
    (ending a conversation, deregistering) stay dashboard-only — this
    page's own script never names either action as a tool call, only a
    plain deep link out (the same ``target="_blank"`` anchor pattern
    ``test_apps_market.py`` asserts for its own "Install" control)."""
    for forbidden in ("directory_deregister", "end_conversation", "/end"):
        assert forbidden not in _SCRIPT_JS
    assert 'target="_blank"' in _SCRIPT_JS
    assert "manageHref" in _SCRIPT_JS


def test_team_mount_present_only_with_both_services() -> None:
    without_either = create_app(HubConfig())
    with TestClient(without_either) as rest:
        assert rest.get("/mcp/team").status_code == 404

    directory = DirectoryService(DirectoryStore(":memory:"))
    only_directory = create_app(HubConfig(), directory_service=directory)
    with TestClient(only_directory) as rest:
        assert rest.get("/mcp/team").status_code == 404

    messenger = MessengerService(MessengerStore(":memory:"), directory)
    both = create_app(
        HubConfig(), directory_service=directory, messenger_service=messenger
    )
    with TestClient(both) as rest:
        # 406, not 404 — same "the mount exists" proof the hub_status/
        # market mount tests use (see test_apps_hub_status.py's docstring).
        assert rest.get("/mcp/team").status_code == 406
