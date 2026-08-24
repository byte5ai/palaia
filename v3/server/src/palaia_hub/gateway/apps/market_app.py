"""Marketplace MCP App (SPEC-304 deliverable #5, MASTERPLAN §5.7 table).

Browse/search as a card grid inside the client, with an inline detail
view (permissions, maintainer, verified state) — the same
:class:`~palaia_hub.market.models.MarketEntry` shape the dashboard's own
marketplace screen reads, so nothing here special-cases a source either.

**"Install itself always deep-links to the dashboard consent screen — the
app never performs the install"** (the SPEC's own words, restating
MASTERPLAN §5.7's "security-sensitive administration stays
dashboard-only"). This page contains no install tool call at all: its
"Install" control is a plain ``<a target="_blank">`` to this hub's
dashboard, built server-side from ``config.exposure.public_url`` (the same
field the exposure wizard already fills in — SPEC-205) — never a guess at
an origin the sandboxed app iframe cannot reliably know. A hub with no
public URL recorded yet (the common case for a brand-new locked-mode hub)
shows plain instructions instead of a dead link, same "never a dead end"
posture :mod:`palaia_hub.gateway.apps.hub_status_app` and the dashboard's
own Clients screen already hold to.
"""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from ...market.models import MarketEntry
from ...market.service import MarketService
from .shell import render_app_page

RESOURCE_URI = "ui://palaia/marketplace.html"

_TITLE = "palaia · Marketplace"

#: How many results the plain-text fallback (a host without the MCP Apps
#: extension) lists — deliverable #5's "plain-text fallback lists top
#: results".
_TEXT_FALLBACK_LIMIT = 10


class MarketBrowseEntry(BaseModel):
    """One card — the fields the grid *and* its inline detail view need."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    one_liner: str
    kind: str
    verified: bool
    provenance: str
    maintainer: str
    permissions: list[str] = Field(default_factory=list)


class MarketBrowseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    entries: list[MarketBrowseEntry] = Field(default_factory=list)
    stale: bool = False
    #: This hub's dashboard, if known (``config.exposure.public_url`` —
    #: SPEC-205) — the base every "Install" deep link is built from. ``None``
    #: means the page shows plain instructions instead of a link (see the
    #: module docstring).
    dashboard_url: str | None = None


def _to_browse_entry(entry: MarketEntry) -> MarketBrowseEntry:
    return MarketBrowseEntry(
        id=entry.id,
        name=entry.name,
        one_liner=entry.one_liner,
        kind=entry.kind,
        verified=entry.verified,
        provenance=entry.provenance,
        maintainer=entry.maintainer,
        permissions=list(entry.permissions),
    )


class MarketAppDeps:
    """State ``browse_marketplace`` reads — a plain bag, mirroring
    :class:`~palaia_hub.gateway.apps.hub_status_app.HubStatusDeps`."""

    def __init__(self, *, market_service: MarketService, dashboard_url: str | None) -> None:
        self.market_service = market_service
        self.dashboard_url = dashboard_url


async def collect_market_browse(deps: MarketAppDeps, query: str = "") -> MarketBrowseResult:
    result = await deps.market_service.search(query)
    return MarketBrowseResult(
        query=query,
        entries=[_to_browse_entry(e) for e in result.entries],
        stale=result.stale,
        dashboard_url=deps.dashboard_url,
    )


def _text_summary(result: MarketBrowseResult) -> str:
    if not result.entries:
        return "No marketplace entries matched." if result.query else "The marketplace is empty."
    lines = [
        f"{'Search' if result.query else 'Browse'} results"
        f"{f' for {result.query!r}' if result.query else ''} "
        f"({len(result.entries)} found, showing up to {_TEXT_FALLBACK_LIMIT}):"
    ]
    for entry in result.entries[:_TEXT_FALLBACK_LIMIT]:
        mark = "verified" if entry.verified else "unverified"
        lines.append(f"- {entry.name} ({entry.kind}, {mark}) — {entry.one_liner}")
    if result.dashboard_url:
        lines.append(f"Install any of these from the dashboard: {result.dashboard_url}/marketplace")
    else:
        lines.append("Install from this hub's dashboard, under Marketplace.")
    return "\n".join(lines)


_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-marketplace", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");
  var state = { entries: [], dashboardUrl: null, openId: null };

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function installHref(id) {
    if (!state.dashboardUrl) return null;
    var base = state.dashboardUrl.replace(/\/+$/, "");
    return base + "/marketplace?install=" + encodeURIComponent(id);
  }

  function render() {
    if (!state.entries.length) {
      root.innerHTML = '<div class="empty">No marketplace entries yet.</div>';
      return;
    }
    var html = '<div class="stack stack--2">';
    for (var i = 0; i < state.entries.length; i++) {
      var e = state.entries[i];
      var open = state.openId === e.id;
      html += '<div class="card">'
        + '<div class="card__head" data-idx="' + i + '" style="cursor:pointer">'
        + '<div><span class="card__title">' + escapeHtml(e.name) + '</span>'
        + '<div class="t-xs t-muted">' + escapeHtml(e.one_liner) + '</div></div>'
        + '<span class="badge ' + (e.verified ? 'badge--ok' : 'badge--warn') + '">'
        + '<span class="dot"></span>' + (e.verified ? 'verified' : 'unverified') + '</span>'
        + '</div>';
      if (open) {
        var href = installHref(e.id);
        var subline = escapeHtml(e.kind) + ' · ' + escapeHtml(e.maintainer);
        html += '<div class="card__body stack stack--2">'
          + '<div class="t-xs t-subtle">' + subline + '</div>';
        if (e.permissions && e.permissions.length) {
          var perms = escapeHtml(e.permissions.join(", "));
          html += '<div class="t-xs t-muted">Permissions: ' + perms + '</div>';
        }
        if (href) {
          html += '<a class="btn btn--primary" href="' + href + '" target="_blank" rel="noopener">'
            + 'Install and connect' + '</a>';
        } else {
          html += '<p class="t-xs t-muted">Open this hub&rsquo;s dashboard, then Marketplace, '
            + 'to install.</p>';
        }
        html += '</div>';
      }
      html += '</div>';
    }
    html += '</div>';
    root.innerHTML = html;
    var heads = root.querySelectorAll("[data-idx]");
    for (var j = 0; j < heads.length; j++) {
      heads[j].addEventListener("click", (function (idx) {
        return function () {
          var id = state.entries[idx].id;
          state.openId = state.openId === id ? null : id;
          render();
        };
      })(Number(heads[j].getAttribute("data-idx"))));
    }
  }

  function loadFromResult(sc) {
    sc = sc || {};
    state.entries = Array.isArray(sc.entries) ? sc.entries : [];
    state.dashboardUrl = sc.dashboard_url || null;
    render();
  }

  app.addEventListener("toolresult", function (params) {
    loadFromResult(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_marketplace_html() -> str:
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


def build_market_server(deps: MarketAppDeps) -> FastMCP:
    """The standalone hub-level ``browse_marketplace`` tool server, mounted
    at ``/mcp/market`` by :func:`palaia_hub.app.create_app` — mirrors
    :func:`~palaia_hub.gateway.apps.hub_status_app.build_hub_status_server`'s
    shape for this SPEC's one hub-level app."""
    server = FastMCP(
        name="palaia-marketplace",
        instructions=(
            "IDENTITY: this is the palaia marketplace — browse and search add-ons "
            "(remote tools, containerized servers, skills). Call browse_marketplace "
            "with a search phrase, or with no arguments to see what's available. "
            "Installing is done from this hub's own dashboard, never from here."
        ),
    )

    @server.tool(
        name="browse_marketplace",
        description=(
            "Browse or search palaia's marketplace of add-ons. Returns a card grid "
            "in clients that render it, or a plain list otherwise. Installing an "
            "entry always opens this hub's dashboard — this tool never installs "
            "anything itself."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=RESOURCE_URI),
    )
    async def browse_marketplace(query: str = "") -> ToolResult:
        result = await collect_market_browse(deps, query)
        return ToolResult(content=_text_summary(result), structured_content=result)

    @server.resource(RESOURCE_URI, name="marketplace_app")
    def _market_resource() -> str:
        return render_marketplace_html()

    return server


__all__ = [
    "RESOURCE_URI",
    "MarketAppDeps",
    "MarketBrowseEntry",
    "MarketBrowseResult",
    "build_market_server",
    "collect_market_browse",
    "render_marketplace_html",
]
