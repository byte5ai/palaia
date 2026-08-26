"""Recall explorer MCP App (SPEC-208 deliverable #3).

Attached to the ``search`` and ``recall`` tools via ``meta.ui.resourceUri``
(:mod:`palaia_hub.gateway.memory_tools`) — a host that renders MCP Apps
shows this page instead of (never *only* instead of: SPEC-105 already gives
every tool result both a human-readable ``content`` string and a
``structured_content`` payload, so a host without the extension gets a
perfectly usable text result either way — deliverable #5) the tool's plain
result.

**Selective context** (MASTERPLAN §5.7, this SPEC's headline mechanism):
the page renders every hit compactly — title, permalink, and a short
snippet, exactly the shape ``search``/``recall`` already return (SPEC-105's
``SearchHit`` carries no note body at all; SPEC-106's ``RecallEntry`` does,
but this page only ever *reads* its ``snippet`` field for display). Nothing
beyond that goes anywhere near the model until the user clicks "Add to
context" on one result. That click calls this vault's ``recall_pick`` tool
— its exact mounted name arrives in the very tool result that rendered this
page, as ``pick_tool`` (see ``vault_protocol.ReviewQueueResult``'s
docstring for why: this page is one static resource shared by every vault
mounted in a profile, so it cannot hard-code a vault-specific, namespaced
tool name — the per-call ``structured_content`` is the layer that already
varies per vault, so that is where the callback name travels) — for
*exactly* that one ref, then hands the returned note straight to
``app.updateModelContext`` (the MCP Apps view SDK's actual host-context
API). Only the picked note's content ever reaches that call.

:func:`build_context_update` is the pure half of that last step, exposed
separately so ``server/tests/gateway/test_apps_recall_explorer.py`` can
assert on the exact ``updateModelContext`` payload without a browser — the
page's own JS (:data:`_SCRIPT_JS`) builds the identical shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..vault_protocol import NoteRecord
from .shell import render_app_page

RESOURCE_URI = "ui://palaia/recall_explorer.html"

_TITLE = "palaia · Recall explorer"

_BODY_HTML = '<div id="root" class="stack"><div class="empty">Loading…</div></div>'

_SCRIPT_JS = r"""
(function () {
  var app = new window.McpAppLib.App({ name: "palaia-recall-explorer", version: "1.0.0" }, {});
  var transport = new window.McpAppLib.PostMessageTransport(window.parent, window.parent);
  var root = document.getElementById("root");
  var state = { kind: "", hits: [], pickTool: "" };

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render() {
    if (!state.hits.length) {
      root.innerHTML = '<div class="empty">No results.</div>';
      return;
    }
    var html = '<div class="card"><div class="card__head"><span class="card__title">'
      + escapeHtml(state.kind) + " · " + state.hits.length + " result(s)</span></div><div>";
    for (var i = 0; i < state.hits.length; i++) {
      var hit = state.hits[i];
      html += '<div class="listrow"><div style="flex:1;min-width:0">'
        + '<div class="listrow__title">' + escapeHtml(hit.title) + "</div>"
        + '<div class="listrow__meta t-mono">' + escapeHtml(hit.permalink) + "</div>"
        + (hit.snippet ? '<div class="listrow__snippet">' + escapeHtml(hit.snippet) + "</div>" : "")
        + '</div><button class="btn btn--primary" data-idx="' + i + '" '
        + (state.pickTool ? "" : "disabled") + ">Add to context</button></div>";
    }
    html += "</div></div>";
    root.innerHTML = html;
    var buttons = root.querySelectorAll("button[data-idx]");
    for (var j = 0; j < buttons.length; j++) {
      buttons[j].addEventListener("click", (function (btn) {
        return function () { pick(Number(btn.getAttribute("data-idx"))); };
      })(buttons[j]));
    }
  }

  function buildContextUpdate(notes) {
    var blocks = [];
    for (var i = 0; i < notes.length; i++) {
      var n = notes[i];
      var body = n.resolved_body || n.body || "";
      blocks.push("## " + n.title + "\nmemory://" + n.permalink + "\n\n" + body.trim() + "\n");
    }
    return {
      content: [{ type: "text", text: blocks.join("\n\n") }],
      structuredContent: { notes: notes },
    };
  }

  function pick(idx) {
    var hit = state.hits[idx];
    if (!state.pickTool || !hit) return;
    app.callServerTool({ name: state.pickTool, arguments: { refs: [hit.permalink] } })
      .then(function (result) {
        if (result.isError) return;
        var notes = (result.structuredContent && result.structuredContent.notes) || [];
        if (!notes.length) return;
        return app.updateModelContext(buildContextUpdate(notes));
      });
  }

  function loadFromResult(sc) {
    sc = sc || {};
    if (Array.isArray(sc.hits)) {
      state.kind = "search";
      state.hits = sc.hits;
      state.pickTool = sc.pick_tool || "";
    } else if (Array.isArray(sc.entries)) {
      state.kind = "recall";
      state.hits = sc.entries.map(function (e) {
        return { title: e.title, permalink: e.permalink, snippet: e.snippet };
      });
      state.pickTool = sc.pick_tool || "";
    } else {
      state.kind = "";
      state.hits = [];
      state.pickTool = "";
    }
    render();
  }

  app.addEventListener("toolresult", function (params) {
    loadFromResult(params.structuredContent);
  });

  app.connect(transport);
})();
"""


def render_recall_explorer_html() -> str:
    """The recall-explorer page — identical for every vault (see module docstring)."""
    return render_app_page(title=_TITLE, body_html=_BODY_HTML, script_js=_SCRIPT_JS)


def build_context_update(notes: Sequence[NoteRecord]) -> dict[str, Any]:
    """The exact ``updateModelContext`` params for the given picked notes.

    Mirrors ``buildContextUpdate`` in :data:`_SCRIPT_JS` field for field.
    Kept here as a pure function so the "selective context" acceptance
    criterion — picking one of N results injects only that one — is
    assertable directly against a real payload shape, without driving a
    browser.
    """
    blocks = []
    for note in notes:
        body = note.resolved_body or note.body
        blocks.append(f"## {note.title}\nmemory://{note.permalink}\n\n{body.strip()}\n")
    return {
        "content": [{"type": "text", "text": "\n\n".join(blocks)}],
        "structuredContent": {"notes": [n.model_dump(mode="json") for n in notes]},
    }


__all__ = ["RESOURCE_URI", "build_context_update", "render_recall_explorer_html"]
