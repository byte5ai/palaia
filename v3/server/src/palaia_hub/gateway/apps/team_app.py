"""Session-monitor MCP App (SPEC-405 deliverable #3, MASTERPLAN §5.7's
Phase-4 "Session monitor / messenger" row: "live agent directory + message
flows; structured-message compose form").

Its own standalone ``FastMCP`` instance, mounted at ``/mcp/team`` — same
"one hub-level server, not per-vault" shape as
:mod:`~palaia_hub.gateway.apps.hub_status_app` and
:mod:`~palaia_hub.gateway.apps.market_app`, gated on *both* the SPEC-402
directory service and the SPEC-403 messenger service being wired (there is
nothing to monitor without either).

**Why this server carries its own copy of ``messenger_send``.** The
compose form's "Send" action calls back through the MCP Apps bridge
(``app.callServerTool``), which only ever reaches a tool on the *same*
server that served the calling page's ``ui://`` resource — it cannot reach
across to :mod:`palaia_hub.gateway.messenger_tools`'s own ``/mcp/messenger``
mount. So this module registers the identical tool via
:func:`~palaia_hub.gateway.messenger_tools.register_messenger_send_tool` on
*this* server too — one implementation of "send a message", running on two
mounts, not two implementations that could drift. The compose form still
needs the caller's own handle and session secret, exactly as calling
``messenger_send`` on ``/mcp/messenger`` directly would (MASTERPLAN §5.7:
"under the same per-client token and scopes — no second auth surface"; the
SPEC-402 session secret is a second credential by design, reused, never
bypassed, for either mount).

**Read-only for everyone else: no bodies, no destructive controls.** The
directory + flows read (``session_monitor``) never shows a message body
(the flows feed here is metadata only, same as the dashboard's own
``/api/messenger`` mirror) — an MCP App is not the owner's admin surface,
so it gets the same withheld-body treatment every non-owner reader does.
Ending a conversation and deregistering a session are the SPEC-304 rule
this SPEC inherits: dashboard-only. This page never calls a tool for
either — it deep-links to the dashboard's Agents screen instead, the exact
"Install itself always deep-links..." pattern
:mod:`~palaia_hub.gateway.apps.market_app` already established for its own
destructive-elsewhere action.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from ...auth.enforcement import missing_directory_scope_error, missing_messenger_scope_error
from ...directory.models import SessionRecord
from ...directory.service import DirectoryService
from ...messenger.models import EnvelopeMetadata
from ...messenger.service import MessengerService
from ..messenger_tools import register_messenger_send_tool
from .shell import render_app_page

RESOURCE_URI = "ui://palaia/team.html"

_TITLE = "palaia · Agents"

#: How many recent flows `session_monitor` renders — a monitor panel, not
#: a full message archive (same reasoning as
#: `~palaia_hub.gateway.apps.market_app`'s text-fallback limit, applied to
#: the structured payload here rather than only the text one).
_FLOW_LIMIT = 30


class TeamMonitorResult(BaseModel):
    """``session_monitor``'s result: the live directory, recent message
    flows (metadata only — no bodies, see the module docstring), which
    tool the compose form calls, and this hub's dashboard for the
    destructive controls this app never performs itself."""

    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionRecord] = Field(default_factory=list)
    flows: list[EnvelopeMetadata] = Field(default_factory=list)
    #: Always ``"messenger_send"`` — named explicitly (rather than assumed)
    #: so the page's own script never hard-codes a tool name it did not
    #: get from a result, the same discipline
    #: `~palaia_hub.gateway.apps.recall_app`'s `pick_tool` field documents.
    send_tool: str = "messenger_send"
    #: This hub's dashboard, if known (`config.exposure.public_url`) — the
    #: base the "manage from the dashboard" deep link is built from. `None`
    #: means the page shows plain instructions instead (see
    #: `~palaia_hub.gateway.apps.market_app`'s identical fallback).
    dashboard_url: str | None = None


class TeamAppDeps:
    """State ``session_monitor`` reads — a plain bag, mirroring
    :class:`~palaia_hub.gateway.apps.hub_status_app.HubStatusDeps`."""

    def __init__(
        self,
        *,
        directory_service: DirectoryService,
        messenger_service: MessengerService,
        dashboard_url: str | None,
    ) -> None:
        self.directory_service = directory_service
        self.messenger_service = messenger_service
        self.dashboard_url = dashboard_url


async def collect_team_monitor(deps: TeamAppDeps) -> TeamMonitorResult:
    directory_result = await deps.directory_service.list()
    flows_result = await deps.messenger_service.flows(limit=_FLOW_LIMIT)
    return TeamMonitorResult(
        sessions=directory_result.sessions,
        flows=flows_result.flows,
        dashboard_url=deps.dashboard_url,
    )


def _text_summary(result: TeamMonitorResult) -> str:
    """The plain-text fallback (SPEC-405 deliverable #3): a compact
    directory listing, for a host with no MCP Apps extension."""
    if not result.sessions:
        return "No agents are registered with this hub right now."
    lines = [f"{len(result.sessions)} agent(s) registered:"]
    for session in result.sessions:
        platform = session.platform or "unknown platform"
        scope = session.scope or "no scope reported"
        lines.append(f"- {session.handle} ({platform}, {session.status}) — {scope}")
    if result.flows:
        lines.append(f"{len(result.flows)} recent message(s) — see the dashboard to read them.")
    return "\n".join(lines)


_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-team", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");
  var state = { sessions: [], flows: [], sendTool: "messenger_send", dashboardUrl: null };
  var composeOpen = false;
  var sending = false;
  var sendError = "";

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function manageHref() {
    if (!state.dashboardUrl) return null;
    return state.dashboardUrl.replace(/\/+$/, "") + "/agents";
  }

  function statusBadgeClass(status) {
    if (status === "stale") return "badge--risk";
    if (status === "idle") return "badge--warn";
    return "badge--ok";
  }

  function renderDirectory() {
    if (!state.sessions.length) {
      return '<div class="empty">No agents are registered with this hub right now.</div>';
    }
    var html = "";
    for (var i = 0; i < state.sessions.length; i++) {
      var s = state.sessions[i];
      html += '<div class="listrow"><div style="flex:1;min-width:0">'
        + '<div class="listrow__title t-mono">' + escapeHtml(s.handle) + "</div>"
        + '<div class="listrow__meta">' + escapeHtml(s.scope || "no scope reported") + "</div>"
        + '<div class="listrow__meta">' + escapeHtml(s.platform || "unknown platform")
        + (s.model ? " · " + escapeHtml(s.model) : "") + "</div></div>"
        + '<span class="badge ' + statusBadgeClass(s.status) + '"><span class="dot"></span>'
        + escapeHtml(s.status) + "</span></div>";
    }
    return html;
  }

  function renderFlows() {
    if (!state.flows.length) {
      return '<div class="empty">No messages yet.</div>';
    }
    var html = "";
    for (var i = 0; i < state.flows.length; i++) {
      var f = state.flows[i];
      html += '<div class="listrow"><div style="flex:1;min-width:0">'
        + '<div class="listrow__title">' + escapeHtml(f.subject) + "</div>"
        + '<div class="listrow__meta">' + escapeHtml(f.from) + " &rarr; "
        + escapeHtml(f.recipient) + " · " + escapeHtml(f.type) + "/" + escapeHtml(f.urgency)
        + "</div></div><span class=\"badge\">" + escapeHtml(f.state) + "</span></div>";
    }
    return html;
  }

  function renderCompose() {
    if (!composeOpen) {
      return '<button class="btn btn--primary" id="open-compose">Send a message</button>';
    }
    var html = '<div class="card"><div class="card__body stack stack--2">'
      + '<div class="t-xs t-muted">Sends over your own connection, with your own handle and '
      + 'secret — the same as calling messenger_send yourself.</div>'
      + '<input class="input" id="f-handle" placeholder="Your agent handle" />'
      + '<input class="input" id="f-secret" type="password" '
      + 'placeholder="Your session secret" />'
      + '<input class="input" id="f-to" '
      + 'placeholder="To (handle, or * / capability:tag for everyone)" />'
      + '<select class="input" id="f-type">'
      + '<option value="inform">Inform</option><option value="request">Request</option>'
      + '<option value="question">Question</option><option value="handoff">Handoff</option>'
      + '<option value="broadcast">Broadcast</option></select>'
      + '<input class="input" id="f-subject" placeholder="Subject" maxlength="200" />'
      + '<textarea class="input" id="f-body" placeholder="Message" rows="3" '
      + 'maxlength="4096"></textarea>'
      + '<select class="input" id="f-urgency">'
      + '<option value="normal">Normal</option><option value="low">Low</option>'
      + '<option value="high">High</option></select>'
      + '<label class="row" style="gap:6px"><input type="checkbox" id="f-reply" />'
      + '<span class="t-sm">Needs a reply</span></label>'
      + (sendError ? '<p class="field__error">' + escapeHtml(sendError) + "</p>" : "")
      + '<div class="row"><button class="btn btn--primary" id="do-send" '
      + (sending ? "disabled" : "") + ">" + (sending ? "Sending…" : "Send") + "</button>"
      + '<button class="btn" id="cancel-compose">Cancel</button></div>'
      + "</div></div>";
    return html;
  }

  function render() {
    var href = manageHref();
    var html = '<div class="row--between">'
      + '<span class="t-xs t-muted">Ending a conversation or removing an agent '
      + 'happens from the dashboard.</span>';
    if (href) {
      html += '<a class="btn" href="' + href + '" target="_blank" rel="noopener">'
        + "Open dashboard</a>";
    }
    html += "</div>";
    html += '<div class="card"><div class="card__head">'
      + '<span class="card__title">Agents</span></div><div>'
      + renderDirectory() + "</div></div>";
    html += '<div class="card"><div class="card__head">'
      + '<span class="card__title">Recent messages</span></div><div>'
      + renderFlows() + "</div></div>";
    html += renderCompose();
    root.innerHTML = html;

    var openBtn = document.getElementById("open-compose");
    if (openBtn) openBtn.addEventListener("click", function () { composeOpen = true; render(); });
    var cancelBtn = document.getElementById("cancel-compose");
    if (cancelBtn) cancelBtn.addEventListener("click", function () {
      composeOpen = false; sendError = ""; render();
    });
    var sendBtn = document.getElementById("do-send");
    if (sendBtn) sendBtn.addEventListener("click", send);
  }

  function fieldValue(id) {
    var el = document.getElementById(id);
    return el ? el.value : "";
  }

  function send() {
    if (sending) return;
    sendError = "";
    var args = {
      handle: fieldValue("f-handle"),
      session_secret: fieldValue("f-secret"),
      to: fieldValue("f-to"),
      message_type: fieldValue("f-type"),
      subject: fieldValue("f-subject"),
      body: fieldValue("f-body"),
      urgency: fieldValue("f-urgency"),
      expects_reply: !!document.getElementById("f-reply").checked,
    };
    if (!args.handle || !args.session_secret || !args.to || !args.subject) {
      sendError = "Fill in your handle, secret, a recipient and a subject.";
      render();
      return;
    }
    sending = true;
    render();
    app.callServerTool({ name: state.sendTool, arguments: args }).then(function (result) {
      sending = false;
      if (result.isError) {
        sendError = (result.content && result.content[0] && result.content[0].text)
          || "Could not send.";
        render();
        return;
      }
      composeOpen = false;
      app.callServerTool({ name: "session_monitor", arguments: {} }).then(function (refreshed) {
        if (!refreshed.isError) loadFromResult(refreshed.structuredContent);
      });
    });
  }

  function loadFromResult(sc) {
    sc = sc || {};
    state.sessions = Array.isArray(sc.sessions) ? sc.sessions : [];
    state.flows = Array.isArray(sc.flows) ? sc.flows : [];
    state.sendTool = sc.send_tool || "messenger_send";
    state.dashboardUrl = sc.dashboard_url || null;
    render();
  }

  app.addEventListener("toolresult", function (params) {
    loadFromResult(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_team_html() -> str:
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


def build_team_server(deps: TeamAppDeps) -> FastMCP:
    """The standalone hub-level ``session_monitor`` (+ ``messenger_send``)
    server, mounted at ``/mcp/team`` by :func:`palaia_hub.app.create_app` —
    mirrors :func:`~palaia_hub.gateway.apps.hub_status_app.
    build_hub_status_server`'s shape."""
    server = FastMCP(
        name="palaia-team",
        instructions=(
            "IDENTITY: this is the team monitor — the live directory of "
            "connected agent sessions and recent message flows for this "
            "palaia hub. Call session_monitor to see who is around and "
            "what has been said (message bodies are not shown here — read "
            "them the same way you always do, with messenger_check/"
            "messenger_thread on your own connection). messenger_send here "
            "is the exact same tool as on the messenger's own connection: "
            "it needs your own handle and session_secret from "
            "directory_register, same as always."
        ),
    )

    @server.tool(
        name="session_monitor",
        description=(
            "The live agent directory and recent message flows (metadata "
            "only — no message bodies). Renders as a panel in clients that "
            "support it, or a compact plain-text listing otherwise."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=RESOURCE_URI),
    )
    async def session_monitor() -> ToolResult:
        # Reuse the directory's/messenger's own established read actions
        # ("directory_list", "messenger_check") to ask for exactly the
        # `directory:read`/`messenger:read` scopes those already carry,
        # rather than adding "session_monitor" to either family's own
        # read-action allow-list — those lists are that family's *own* tool
        # names (asserted exhaustively in
        # ``server/tests/auth/test_directory_scopes.py``/
        # ``test_messenger_scopes.py``), and this tool lives in neither
        # family's server.
        missing = missing_directory_scope_error("directory_list") or missing_messenger_scope_error(
            "messenger_check"
        )
        if missing is not None:
            return ToolResult(content=missing, is_error=True)
        result = await collect_team_monitor(deps)
        return ToolResult(content=_text_summary(result), structured_content=result)

    register_messenger_send_tool(server, deps.messenger_service)

    @server.resource(RESOURCE_URI, name="team_app")
    def _team_resource() -> str:
        return render_team_html()

    return server


__all__ = [
    "RESOURCE_URI",
    "TeamAppDeps",
    "TeamMonitorResult",
    "build_team_server",
    "collect_team_monitor",
    "render_team_html",
]
