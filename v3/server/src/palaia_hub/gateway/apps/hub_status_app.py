"""Hub status MCP App (SPEC-208 deliverable #2).

The first-tool-call orientation panel: health, vaults, index/embed
backlog, and connected clients — everything a "is everything okay?" glance
needs, in one hub-level tool (``hub_status``) rather than one per vault
(unlike the memory tool family, this information is not vault-scoped —
mounting it once per hub, at ``/mcp/hub``, mirrors the stash tool family's
own hub-level mount in :mod:`palaia_hub.gateway.stash_tools`).

Unlike the recall-explorer/review-queue apps, ``hub_status`` needs no
"which tool do I call back" indirection: the app's own refresh action just
calls ``hub_status`` again by its fixed, un-namespaced name.
"""

from __future__ import annotations

import time
from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.server.auth import AuthProvider
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from .shell import render_app_page

RESOURCE_URI = "ui://palaia/hub_status.html"

_TITLE = "palaia · Hub status"


class ClientStatus(BaseModel):
    """One client token's connection health, for the connected-clients tile."""

    model_config = ConfigDict(extra="forbid")

    name: str
    profile: str
    last_used_at: str | None = None


class VaultStatus(BaseModel):
    """One vault's health: identity, size, and embed backlog if indexed."""

    model_config = ConfigDict(extra="forbid")

    key: str
    purpose: str = ""
    note_count: int
    writable: bool
    embed_progress_percent: int | None = None
    embed_summary: str | None = None


class HubStatusResult(BaseModel):
    """What one ``hub_status`` call answers."""

    model_config = ConfigDict(extra="forbid")

    version: str
    mode: str
    uptime_seconds: float
    vaults: list[VaultStatus] = Field(default_factory=list)
    clients: list[ClientStatus] = Field(default_factory=list)


_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-hub-status", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render(sc) {
    sc = sc || {};
    var vaults = Array.isArray(sc.vaults) ? sc.vaults : [];
    var clients = Array.isArray(sc.clients) ? sc.clients : [];
    var html = '<div class="row--between">'
      + '<span class="badge badge--ok"><span class="dot"></span>' + escapeHtml(sc.mode || "")
      + " · v" + escapeHtml(sc.version || "") + "</span>"
      + '<button class="btn" id="refresh">Refresh</button></div>';

    html += '<div class="card"><div class="card__head">'
      + '<span class="card__title">Vaults</span></div><div>';
    if (!vaults.length) {
      html += '<div class="empty">No vaults configured.</div>';
    }
    for (var i = 0; i < vaults.length; i++) {
      var v = vaults[i];
      var backlog = typeof v.embed_progress_percent === "number"
        ? v.embed_summary || (v.embed_progress_percent + "% embedded")
        : "";
      html += '<div class="listrow"><div style="flex:1;min-width:0">'
        + '<div class="listrow__title">' + escapeHtml(v.key) + "</div>"
        + '<div class="listrow__meta">' + escapeHtml(v.purpose || "") + "</div>"
        + "</div><div style=\"text-align:right\">"
        + '<div class="t-mono t-muted">' + v.note_count + " note(s)</div>"
        + (backlog ? '<div class="listrow__meta">' + escapeHtml(backlog) + "</div>" : "")
        + "</div></div>";
    }
    html += "</div></div>";

    html += '<div class="card"><div class="card__head">'
      + '<span class="card__title">Connected clients</span></div><div>';
    if (!clients.length) {
      html += '<div class="empty">No client has connected yet.</div>';
    }
    for (var j = 0; j < clients.length; j++) {
      var c = clients[j];
      html += '<div class="listrow"><div style="flex:1;min-width:0">'
        + '<div class="listrow__title">' + escapeHtml(c.name) + "</div>"
        + '<div class="listrow__meta">' + escapeHtml(c.profile) + "</div>"
        + "</div><div class=\"t-mono t-subtle\">"
        + escapeHtml(c.last_used_at || "never used") + "</div></div>";
    }
    html += "</div></div>";

    root.innerHTML = html;
    var refresh = document.getElementById("refresh");
    if (refresh) {
      refresh.addEventListener("click", function () {
        app.callServerTool({ name: "hub_status", arguments: {} }).then(function (result) {
          if (!result.isError) render(result.structuredContent);
        });
      });
    }
  }

  app.addEventListener("toolresult", function (params) {
    render(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_hub_status_html() -> str:
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


class HubStatusDeps:
    """The hub-wide state ``hub_status`` reads — a plain bag, not a
    protocol: this tool needs whatever the hub happens to have wired at
    ``create_app`` time (a vault registry, indexes, a token store), none of
    which the per-vault :class:`~palaia_hub.gateway.vault_protocol.
    VaultService` surface has any reason to know about.
    """

    def __init__(
        self,
        *,
        vault_registry: Any,
        indexes: dict[str, Any] | None,
        token_store: Any | None,
        mode: str,
        start_time: float,
    ) -> None:
        self.vault_registry = vault_registry
        self.indexes = indexes or {}
        self.token_store = token_store
        self.mode = mode
        self.start_time = start_time


async def collect_hub_status(deps: HubStatusDeps) -> HubStatusResult:
    from ... import __version__
    from ...index import embed_progress

    vaults: list[VaultStatus] = []
    for record in deps.vault_registry.records():
        engine = await deps.vault_registry.get(record.name)
        info = engine.info()
        percent: int | None = None
        summary: str | None = None
        index = deps.indexes.get(record.name)
        if index is not None:
            status = index.status()
            percent, summary = embed_progress(status.embeds)
        vaults.append(
            VaultStatus(
                key=record.name,
                purpose=info.purpose or "",
                note_count=info.note_count,
                writable=info.writable,
                embed_progress_percent=percent,
                embed_summary=summary,
            )
        )

    clients: list[ClientStatus] = []
    if deps.token_store is not None:
        for info in deps.token_store.list_tokens():
            if info.revoked_at is not None:
                continue
            clients.append(
                ClientStatus(name=info.name, profile=info.profile, last_used_at=info.last_used_at)
            )

    return HubStatusResult(
        version=__version__,
        mode=deps.mode,
        uptime_seconds=round(time.monotonic() - deps.start_time, 3),
        vaults=vaults,
        clients=clients,
    )


def build_hub_status_server(deps: HubStatusDeps, *, auth: AuthProvider | None = None) -> FastMCP:
    """The standalone hub-level ``hub_status`` tool server (mounted at
    ``/mcp/hub`` by :func:`palaia_hub.app.create_app`), mirroring
    :func:`palaia_hub.gateway.stash_tools.build_stash_server`'s shape for
    the one hub-level server this SPEC adds.
    """
    server = FastMCP(
        auth=auth,
        name="palaia-hub-status",
        instructions=(
            "IDENTITY: this is the hub status tool — health, vaults, index/embed "
            "backlog and connected clients for this palaia hub. Call it first to "
            "orient yourself; call it again any time to check in."
        ),
    )

    @server.tool(
        name="hub_status",
        description=(
            "Hub health at a glance: version, operating mode, configured vaults "
            "with their size and embedding backlog, and every client that has "
            "connected. The first-call orientation panel."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=RESOURCE_URI),
    )
    async def hub_status() -> ToolResult:
        result = await collect_hub_status(deps)
        text = (
            f"palaia hub v{result.version} ({result.mode}), up "
            f"{result.uptime_seconds:.0f}s — {len(result.vaults)} vault(s), "
            f"{len(result.clients)} client(s) connected"
        )
        return ToolResult(content=text, structured_content=result)

    @server.resource(RESOURCE_URI, name="hub_status_app")
    def _hub_status_resource() -> str:
        return render_hub_status_html()

    return server


__all__ = [
    "RESOURCE_URI",
    "ClientStatus",
    "HubStatusDeps",
    "HubStatusResult",
    "VaultStatus",
    "build_hub_status_server",
    "collect_hub_status",
    "render_hub_status_html",
]
