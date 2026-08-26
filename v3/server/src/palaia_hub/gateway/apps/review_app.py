"""Review queue MCP App (SPEC-208 deliverable #4).

Attached to the ``review_queue`` tool (:mod:`palaia_hub.gateway.
memory_tools`) via ``meta.ui.resourceUri`` — proposal cards with a diff
view and approve/reject actions, mirroring
``v3/docs/design/mockups/review-queue.html`` (the dashboard's own future
screen for the same format-spec §8 contract; this SPEC does not touch that
read-only mockup, only reads it for the Lume token values it already
carries, per :mod:`palaia_hub.gateway.apps.shell`'s docstring).

Approve/reject calls this vault's ``review_decide`` tool — its exact
mounted name arrives in the ``review_queue`` result's own ``decide_tool``
field, same reasoning as the recall-explorer app's ``pick_tool`` (see
:mod:`palaia_hub.gateway.apps.recall_app`'s docstring) — which flips the
proposal's frontmatter ``status`` through the identical
:meth:`~palaia_hub.gateway.vault_protocol.VaultService.review_decide` call
the dashboard's own ``POST /api/vaults/{vault_key}/review/{permalink}/
decision`` REST endpoint uses (:mod:`palaia_hub.dashboard_api`) — "approve
from the app flips the status exactly like the dashboard path" because both
paths are the same one line of code underneath.
"""

from __future__ import annotations

from .shell import render_app_page

RESOURCE_URI = "ui://palaia/review_queue.html"

_TITLE = "palaia · Review queue"

_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-review-queue", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");
  var state = { proposals: [], decideTool: "" };

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function badgeClass(status) {
    if (status === "approved" || status === "applied") return "badge--ok";
    if (status === "rejected" || status === "apply-failed") return "badge--risk";
    return "";
  }

  function render() {
    if (!state.proposals.length) {
      root.innerHTML = '<div class="empty">Nothing awaiting review.</div>';
      return;
    }
    var html = "";
    for (var i = 0; i < state.proposals.length; i++) {
      var p = state.proposals[i];
      var pending = p.status === "proposed";
      html += '<div class="card" style="margin-bottom:12px">'
        + '<div class="card__head"><span class="card__title">' + escapeHtml(p.title) + "</span>"
        + '<span class="badge ' + badgeClass(p.status) + '"><span class="dot"></span>'
        + escapeHtml(p.status) + "</span></div>"
        + '<div class="card__body stack--2">'
        + '<div class="diff">' + escapeHtml(p.body) + "</div>";
      if (pending && state.decideTool) {
        html += '<div class="row">'
          + '<button class="btn btn--primary" data-action="approved" data-idx="'
          + i + '">Approve</button>'
          + '<button class="btn btn--risk" data-action="rejected" data-idx="'
          + i + '">Reject</button>'
          + "</div>";
      }
      html += "</div></div>";
    }
    root.innerHTML = html;
    var buttons = root.querySelectorAll("button[data-action]");
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].addEventListener("click", (function (btn) {
        return function () {
          decide(Number(btn.getAttribute("data-idx")), btn.getAttribute("data-action"));
        };
      })(buttons[j]));
    }
  }

  function decide(idx, decision) {
    var p = state.proposals[idx];
    if (!p || !state.decideTool) return;
    app.callServerTool({
      name: state.decideTool,
      arguments: { permalink: p.permalink, decision: decision },
    }).then(function (result) {
      if (result.isError) return;
      p.status = decision;
      render();
    });
  }

  function loadFromResult(sc) {
    sc = sc || {};
    state.proposals = Array.isArray(sc.proposals) ? sc.proposals : [];
    state.decideTool = sc.decide_tool || "";
    render();
  }

  app.addEventListener("toolresult", function (params) {
    loadFromResult(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_review_queue_html() -> str:
    """The review-queue page — identical for every vault (see module docstring)."""
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


__all__ = ["RESOURCE_URI", "render_review_queue_html"]
