"""The MCP App shell: self-containment (CSP), theme tokens, and the
vendored bridge script (SPEC-208 deliverable #1 + the "zero external
network requests" acceptance criterion).

**"Scripted harness" note** (documenting the approach the SPEC asks for):
this repo has no browser-automation dependency (no Playwright/Selenium in
either the Python or the ``v3/web`` toolchain), so full DOM-level
rendering of these pages is not driven by an automated headless browser
here. What *is* driven, automatically, in this file and in
``test_apps_hub_status.py`` / ``test_apps_recall_explorer.py`` /
``test_apps_review_queue.py``:

1. The real MCP tool/resource protocol, end to end, through
   :class:`fastmcp.Client` — every tool a page attaches to, the resource
   URI it points at, and (for recall-explorer/review-queue) the callback
   tool an "Add to context"/"Approve" click would invoke — proven against
   the real gateway mount, not a mock.
2. The vendored MCP Apps view SDK bundle itself (below): loaded and
   exercised in a real Node process (this repo already depends on Node for
   ``v3/web``), confirming the exact classes the pages' own script expects
   (``App``, ``PostMessageTransport``) are present and constructible from
   the byte-for-byte file every page embeds.
3. This module's CSP scan: a static analysis of the produced HTML for the
   handful of constructs that actually cause a browser to make a network
   request (``<script src=``, ``<link href=``, ``@import url(``,
   ``fetch(``, ``XMLHttpRequest``, ``new WebSocket(``) — deliberately not a
   blanket scan for the substring ``"https://"``, which would also flag
   inert string literals already present in the vendored library (URL
   constructor calls used for IPv6 validation, JSON-Schema ``$schema``
   comparison strings) that never cause a request.

What is not covered: a click actually re-rendering the DOM inside a real
iframe. Given no browser-automation tool exists in this environment/repo,
closing that gap would mean adding a new dependency (e.g. Playwright) —
judged out of proportion for this SPEC; the page scripts are deliberately
simple, template-string-and-innerHTML renderers with no logic of their own
beyond string concatenation, and the one piece of real behavioral risk —
selective context's exact payload — is covered by a pure function
(:func:`~palaia_hub.gateway.apps.recall_app.build_context_update`) asserted
directly in ``test_apps_recall_explorer.py``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from palaia_hub.gateway.apps.hub_status_app import render_hub_status_html
from palaia_hub.gateway.apps.recall_app import render_recall_explorer_html
from palaia_hub.gateway.apps.review_app import render_review_queue_html
from palaia_hub.gateway.apps.shell import render_app_page

_PAGES = {
    "hub_status": render_hub_status_html,
    "recall_explorer": render_recall_explorer_html,
    "review_queue": render_review_queue_html,
}

# Constructs that cause a browser to make a network request. Not "https://"
# as a bare substring — see the module docstring for why.
_NETWORK_PATTERNS = [
    re.compile(r"<script[^>]+src\s*=", re.IGNORECASE),
    re.compile(r"<link[^>]+href\s*=", re.IGNORECASE),
    re.compile(r"@import\s+url\(", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bnew\s+WebSocket\s*\("),
]


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_page_makes_zero_external_network_requests(name: str) -> None:
    html = _PAGES[name]()
    for pattern in _NETWORK_PATTERNS:
        assert not pattern.search(html), (
            f"{name} page contains a network-request construct: {pattern.pattern}"
        )


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_page_is_one_self_contained_document_with_a_csp_meta_tag(name: str) -> None:
    html = _PAGES[name]()
    assert html.startswith("<!doctype html>")
    assert "<meta http-equiv=\"Content-Security-Policy\"" in html
    assert "default-src 'none'" in html
    # Fonts and the bridge script are inline, not referenced.
    assert "data:font/woff2;base64," in html
    assert "window.McpAppLib" in html


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_page_carries_theme_aware_tokens_for_both_color_schemes(name: str) -> None:
    html = _PAGES[name]()
    assert "prefers-color-scheme:dark" in html
    assert '[data-theme="dark"]' in html


def test_render_app_page_escapes_a_hostile_title() -> None:
    html = render_app_page(body_html="<div></div>", script_js="", title="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_vendored_bridge_exposes_the_expected_view_sdk_classes() -> None:
    """Run the exact, byte-for-byte vendored file every page embeds in a
    real Node process and assert it exposes ``window.McpAppLib.{App,
    PostMessageTransport}`` as constructible classes — the automated,
    non-mocked half of "does the bridge script actually work" this test
    suite can check without a browser."""
    bridge_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "palaia_hub"
        / "gateway"
        / "apps"
        / "vendor"
        / "mcp_app_bridge.js"
    )
    assert bridge_path.is_file()
    probe = (
        "global.window = {};"
        f"eval(require('fs').readFileSync({str(bridge_path)!r}, 'utf8'));"
        "if (typeof window.McpAppLib.App !== 'function') throw new Error('App missing');"
        "if (typeof window.McpAppLib.PostMessageTransport !== 'function')"
        " throw new Error('PostMessageTransport missing');"
        "console.log('ok');"
    )
    result = subprocess.run(
        ["node", "-e", probe], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
