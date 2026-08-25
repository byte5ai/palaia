"""Stash browser MCP App (SPEC-405 deliverable #4, MASTERPLAN §5.7's
Phase-4 "Stash browser" row: "cache entries with TTL/size ... inspection
utility").

Attached to a new ``stash_browse`` tool in
:mod:`palaia_hub.gateway.stash_tools` via ``meta.ui.resourceUri`` — the same
"attach an app to an existing family's own tool" shape SPEC-208 already used
for ``review_queue``/``search``/``recall`` (:mod:`palaia_hub.gateway.
memory_tools`), applied here to the stash family instead of the memory one.
The stash is a hub-level singleton (one per hub, not one per vault), so —
like :mod:`~palaia_hub.gateway.apps.hub_status_app` and
:mod:`~palaia_hub.gateway.apps.market_app` — its tool and its ``ui://``
resource are registered on the *same* ``FastMCP`` instance rather than
needing the shared-registration indirection the per-vault memory family
uses.

**Small by design, on purpose (the SPEC's own words).** ``stash_browse``
never returns a stored *value* — only ``namespace``/``key``/``size_bytes``/
expiry/staleness. A cache entry can hold anything (a job's working state, a
rate-limit counter, a draft) and this is an inspection utility, not a
viewer: seeing what is cached, how big it is and when it expires answers
"is the stash doing something sane" without dumping arbitrary cached data
into a chat transcript. Reading one entry's actual value still works, the
same way it always has, via ``stash_get`` — this app just never calls it.

**Two levels, one tool, same shape as** :mod:`~palaia_hub.gateway.
apps.hub_status_app`'s "call the same tool again to refresh": an empty
``namespace`` argument renders the namespace overview (counts, total size,
budget); passing one of those namespaces back in renders that namespace's
entries. No second tool, no drill-down tool name to thread through
``structured_content`` — the one tool answers both questions depending on
what it is asked.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ...stash.models import StashEntry
from ...stash.service import StashService
from .shell import render_app_page

RESOURCE_URI = "ui://palaia/stash_browser.html"

_TITLE = "palaia · Stash browser"


class StashBrowseEntry(BaseModel):
    """One cache entry, minus its value (see the module docstring)."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    key: str
    size_bytes: int
    created_at: float
    updated_at: float
    expires_at: float | None
    stale: bool


class StashBrowseResult(BaseModel):
    """``stash_browse``'s result: the namespace overview, or one
    namespace's entries — see the module docstring for which."""

    model_config = ConfigDict(extra="forbid")

    #: The namespace this result drills into, or ``""`` for the overview.
    namespace: str = ""
    #: Every namespace's entry count (from ``stash_status``) — always
    #: present, so the overview and a drill-down both know what else there
    #: is to look at.
    namespaces: dict[str, int] = Field(default_factory=dict)
    total_entries: int = 0
    total_bytes: int = 0
    budget_bytes: int = 0
    #: This namespace's entries, minus their values. Empty at the overview
    #: level (``namespace == ""``).
    entries: list[StashBrowseEntry] = Field(default_factory=list)


def _to_browse_entry(namespace: str, entry: StashEntry) -> StashBrowseEntry:
    return StashBrowseEntry(
        namespace=namespace,
        key=entry.key,
        size_bytes=entry.size_bytes,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        expires_at=entry.expires_at,
        stale=entry.stale,
    )


async def collect_stash_browse(service: StashService, namespace: str = "") -> StashBrowseResult:
    status = await service.status()
    namespace = namespace.strip()
    entries: list[StashBrowseEntry] = []
    if namespace:
        listing = await service.list(namespace)
        entries = [_to_browse_entry(namespace, entry) for entry in listing.entries]
    return StashBrowseResult(
        namespace=namespace,
        namespaces=dict(status.namespaces),
        total_entries=status.total_entries,
        total_bytes=status.total_bytes,
        budget_bytes=status.budget_bytes,
        entries=entries,
    )


def stash_browse_summary(result: StashBrowseResult) -> str:
    if not result.namespace:
        if not result.namespaces:
            return "The stash is empty."
        parts = ", ".join(f"{ns} ({count})" for ns, count in result.namespaces.items())
        return (
            f"{result.total_entries} entries, {result.total_bytes}/{result.budget_bytes} "
            f"bytes used, across {len(result.namespaces)} namespace(s): {parts}"
        )
    if not result.entries:
        return f"namespace {result.namespace!r} has no entries."
    lines = [f"{len(result.entries)} entr{'y' if len(result.entries) == 1 else 'ies'} "
             f"in {result.namespace!r}:"]
    for entry in result.entries:
        stale_note = " (stale)" if entry.stale else ""
        expiry = "no expiry" if entry.expires_at is None else f"expires {entry.expires_at:.0f}"
        lines.append(f"- {entry.key}: {entry.size_bytes} bytes, {expiry}{stale_note}")
    return "\n".join(lines)


_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-stash-browser", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");
  var state = { namespace: "", namespaces: {}, entries: [] };

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function browse(namespace) {
    app.callServerTool({ name: "stash_browse", arguments: { namespace: namespace } })
      .then(function (result) {
        if (!result.isError) loadFromResult(result.structuredContent);
      });
  }

  function render() {
    var html = "";
    if (state.namespace) {
      html += '<div class="row" style="margin-bottom:8px">'
        + '<button class="btn" id="back">&larr; All namespaces</button></div>';
      html += '<div class="card"><div class="card__head"><span class="card__title">'
        + escapeHtml(state.namespace) + "</span></div><div>";
      if (!state.entries.length) {
        html += '<div class="empty">No entries in this namespace.</div>';
      }
      for (var i = 0; i < state.entries.length; i++) {
        var e = state.entries[i];
        var expiry = e.expires_at == null
          ? "no expiry"
          : "expires " + new Date(e.expires_at * 1000).toLocaleString();
        html += '<div class="listrow"><div style="flex:1;min-width:0">'
          + '<div class="listrow__title t-mono">' + escapeHtml(e.key) + "</div>"
          + '<div class="listrow__meta">' + expiry + (e.stale ? " · stale" : "") + "</div>"
          + '</div><div class="t-mono t-muted">' + e.size_bytes + " bytes</div></div>";
      }
      html += "</div></div>";
    } else {
      var names = Object.keys(state.namespaces);
      html += '<div class="card"><div class="card__head">'
        + '<span class="card__title">Namespaces</span></div><div>';
      if (!names.length) {
        html += '<div class="empty">The stash is empty.</div>';
      }
      for (var j = 0; j < names.length; j++) {
        var name = names[j];
        html += '<div class="listrow" data-ns="' + escapeHtml(name) + '" style="cursor:pointer">'
          + '<div style="flex:1;min-width:0"><div class="listrow__title">'
          + escapeHtml(name) + "</div></div>"
          + '<div class="t-mono t-muted">' + state.namespaces[name] + " entr"
          + (state.namespaces[name] === 1 ? "y" : "ies") + "</div></div>";
      }
      html += "</div></div>";
    }
    root.innerHTML = html;
    var back = document.getElementById("back");
    if (back) back.addEventListener("click", function () { browse(""); });
    var rows = root.querySelectorAll("[data-ns]");
    for (var k = 0; k < rows.length; k++) {
      rows[k].addEventListener("click", (function (row) {
        return function () { browse(row.getAttribute("data-ns")); };
      })(rows[k]));
    }
  }

  function loadFromResult(sc) {
    sc = sc || {};
    state.namespace = sc.namespace || "";
    state.namespaces = sc.namespaces || {};
    state.entries = Array.isArray(sc.entries) ? sc.entries : [];
    render();
  }

  app.addEventListener("toolresult", function (params) {
    loadFromResult(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_stash_browser_html() -> str:
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


__all__ = [
    "RESOURCE_URI",
    "StashBrowseEntry",
    "StashBrowseResult",
    "collect_stash_browse",
    "render_stash_browser_html",
    "stash_browse_summary",
]
