"""The shared MCP App shell: one self-contained HTML page builder.

SPEC-208 deliverable #1. Every app this package serves (hub status, recall
explorer, review queue) is rendered by :func:`render_app_page`, which
produces one complete, self-contained ``<!doctype html>`` document:

- **The Lume design tokens** (:data:`LUME_CSS`), the same color/spacing/type
  values ``v3/docs/design/lume/colors_and_type.css`` and the dashboard
  mockups use — copied, not re-derived — plus a small set of components
  (card, badge, button, list row, queue meter) actually needed by these
  three apps. This is a deliberately smaller subset than the dashboard's own
  stylesheet: an MCP App is one compact panel, not a whole application
  shell with a nav rail.
- **Two self-hosted font files** (:data:`FONTS_CSS`), embedded as ``data:``
  URIs from the same WOFF2 files the dashboard build self-hosts
  (``v3/web/src/assets/fonts``, vendored into this package under
  ``vendor/fonts`` so the server wheel does not depend on the ``web/``
  package at runtime — see that directory's docstring). Only the
  non-italic, latin-subset weight-normal files for Geist and Geist Mono are
  embedded: these are compact UI panels, not prose passages, so the serif
  register and the italic/extended-latin cuts are not needed here (a
  genuinely different trade-off than the dashboard build's, which embeds
  every cut).
- **The vendored MCP Apps view SDK** (:data:`_APP_BRIDGE_JS`, from
  ``vendor/mcp_app_bridge.js`` — see that file's own header for provenance),
  giving every page's own script a plain ``window.McpAppLib.{App,
  PostMessageTransport}`` to build on, with no CDN, import map, or bare
  ES-module specifier — the iframe CSP MCP Apps runs under blocks all of
  those (SPEC-208 deliverable #1: "self-contained per the MCP Apps
  extension ... fonts bundled").

Zero external network reference of any kind appears anywhere in the
produced page: no ``<script src=`` / ``<link href=`` / ``@import url(`` /
``fetch(`` / ``XMLHttpRequest`` / ``WebSocket(`` naming an external origin.
``server/tests/gateway/test_apps_shell.py`` asserts exactly that (the CSP
acceptance criterion), by parsing the produced HTML for those constructs
rather than a blanket text scan (a scan for the substring ``"https://"``
would also flag this module's own doc comments once inlined, which name no
live resource).
"""

from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

_VENDOR_DIR = Path(__file__).resolve().parent / "vendor"
_FONTS_DIR = _VENDOR_DIR / "fonts"


@lru_cache(maxsize=1)
def _app_bridge_js() -> str:
    return (_VENDOR_DIR / "mcp_app_bridge.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _font_data_uri(filename: str) -> str:
    raw = (_FONTS_DIR / filename).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:font/woff2;base64,{encoded}"


@lru_cache(maxsize=1)
def _fonts_css() -> str:
    geist = _font_data_uri("geist-latin-wght-normal.woff2")
    geist_mono = _font_data_uri("geist-mono-latin-wght-normal.woff2")
    return f"""
@font-face {{
  font-family: 'Geist Variable';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('{geist}') format('woff2-variations');
}}
@font-face {{
  font-family: 'Geist Mono Variable';
  font-style: normal;
  font-weight: 100 900;
  font-display: swap;
  src: url('{geist_mono}') format('woff2-variations');
}}
"""


#: Design tokens copied verbatim (values, not structure) from
#: ``v3/docs/design/lume/colors_and_type.css`` / the dashboard mockups —
#: "same values as the dashboard" (SPEC-208 deliverable #1) — trimmed to
#: the primitives and components these three compact panels actually use.
#: Light tokens live on bare ``:root``; dark tokens are re-declared both
#: under ``prefers-color-scheme: dark`` (the system default, no explicit
#: host choice) and under ``:root[data-theme="dark"]`` (an explicit host
#: choice always wins) per the theme-aware pattern every self-contained
#: page in this codebase follows.
LUME_CSS = """
:root{
  color-scheme: light dark;
  --space-2:8px; --space-3:12px; --space-4:16px; --space-5:20px; --space-6:24px;
  --radius-sm:6px; --radius-md:8px; --radius-lg:10px; --radius-pill:999px;
  --font-sans:'Geist Variable',system-ui,-apple-system,'Segoe UI',sans-serif;
  --font-mono:'Geist Mono Variable',ui-monospace,'SF Mono',Menlo,Consolas,monospace;

  --bg-canvas-top:#F8F9FA; --bg-canvas-btm:#F4F5F7;
  --bg-surface-top:#FFFFFF; --bg-surface-btm:#FAFBFC;
  --bg-surface-raised-top:#FFFFFF; --bg-surface-raised-btm:#F7F9FB;
  --bg-surface-sunken-top:#F4F5F7; --bg-surface-sunken-btm:#EEF0F2;
  --border-subtle-top:#E6E8EB; --border-subtle-btm:#D9DCDF;
  --text-primary:#1A1D20; --text-secondary:#5A6068; --text-tertiary:#8A9098;
  --text-on-accent:#FFFFFF; --top-edge-highlight:rgba(255,255,255,.60);
  --state-error-fg:#A8443B; --state-error-edge:#C45A50;
  --state-success-fg:#3F7A55; --state-warning-fg:#8C6A1F;
  --accent-fill:#B36B2E; --accent-fill-hover:#9F5C26;
  --accent-subtle:rgba(179,107,46,.10); --accent-glow:rgba(179,107,46,.24);
  --shadow-raised:0 1px 2px rgba(20,25,30,.04), 0 0 0 1px rgba(20,25,30,.02);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg-canvas-top:#232631; --bg-canvas-btm:#1B1D24;
  --bg-surface-top:#2A2D38; --bg-surface-btm:#23262F;
  --bg-surface-raised-top:#303440; --bg-surface-raised-btm:#292C37;
  --bg-surface-sunken-top:#1D1F26; --bg-surface-sunken-btm:#16181E;
  --border-subtle-top:rgba(255,255,255,.06); --border-subtle-btm:rgba(0,0,0,.40);
  --text-primary:#EEEFF3; --text-secondary:#B6B9C3; --text-tertiary:#888B95;
  --text-on-accent:#1F2127; --top-edge-highlight:rgba(255,255,255,.08);
  --state-error-fg:#E08577; --state-error-edge:#C5685A;
  --state-success-fg:#88C499; --state-warning-fg:#D6B468;
  --accent-fill:#E0A26B; --accent-fill-hover:#E5B080;
  --accent-subtle:rgba(224,162,107,.18); --accent-glow:rgba(224,162,107,.30);
  --shadow-raised:0 1px 2px rgba(0,0,0,.30), 0 0 0 1px rgba(0,0,0,.20);
}}
:root[data-theme="dark"]{
  --bg-canvas-top:#232631; --bg-canvas-btm:#1B1D24;
  --bg-surface-top:#2A2D38; --bg-surface-btm:#23262F;
  --bg-surface-raised-top:#303440; --bg-surface-raised-btm:#292C37;
  --bg-surface-sunken-top:#1D1F26; --bg-surface-sunken-btm:#16181E;
  --border-subtle-top:rgba(255,255,255,.06); --border-subtle-btm:rgba(0,0,0,.40);
  --text-primary:#EEEFF3; --text-secondary:#B6B9C3; --text-tertiary:#888B95;
  --text-on-accent:#1F2127; --top-edge-highlight:rgba(255,255,255,.08);
  --state-error-fg:#E08577; --state-error-edge:#C5685A;
  --state-success-fg:#88C499; --state-warning-fg:#D6B468;
  --accent-fill:#E0A26B; --accent-fill-hover:#E5B080;
  --accent-subtle:rgba(224,162,107,.18); --accent-glow:rgba(224,162,107,.30);
  --shadow-raised:0 1px 2px rgba(0,0,0,.30), 0 0 0 1px rgba(0,0,0,.20);
}

*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:linear-gradient(180deg,var(--bg-canvas-top) 0%,var(--bg-canvas-btm) 100%);
  color:var(--text-primary);
  font-family:var(--font-sans);font-size:13px;line-height:1.5;
  padding:var(--space-4);
}
h1,h2,h3,p{margin:0}
button{font:inherit;color:inherit;cursor:pointer}
.t-mono{font-family:var(--font-mono);font-feature-settings:'tnum'}
.t-muted{color:var(--text-secondary)}
.t-subtle{color:var(--text-tertiary)}
.t-over{font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--text-tertiary)}
.stack{display:flex;flex-direction:column;gap:var(--space-4)}
.stack--2{display:flex;flex-direction:column;gap:var(--space-2)}
.row{display:flex;align-items:center;gap:var(--space-3)}
.row--between{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3)}

.card{
  background:linear-gradient(180deg,var(--bg-surface-top) 0%,var(--bg-surface-btm) 100%);
  border:1px solid var(--border-subtle-btm);border-top-color:var(--border-subtle-top);
  border-radius:var(--radius-lg);
  box-shadow:var(--shadow-raised),0 1px 0 var(--top-edge-highlight) inset;
}
.card__head{display:flex;align-items:baseline;justify-content:space-between;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle-btm)}
.card__title{font-size:12px;font-weight:500;letter-spacing:.02em;color:var(--text-secondary)}
.card__body{padding:var(--space-4)}

.tile{
  background:linear-gradient(180deg,var(--bg-surface-raised-top) 0%,
    var(--bg-surface-raised-btm) 100%);
  border:1px solid var(--border-subtle-btm);border-top-color:var(--border-subtle-top);
  border-radius:var(--radius-md);padding:var(--space-3) var(--space-4);
  display:flex;flex-direction:column;gap:4px;
}
.tile__metric{font-family:var(--font-mono);font-size:20px;font-weight:500;font-feature-settings:'tnum'}
.tile__label{font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--text-tertiary)}

.badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text-secondary)}
.badge .dot{width:6px;height:6px;border-radius:50%;background:var(--text-tertiary);flex:none}
.badge--ok .dot{background:var(--state-success-fg)}
.badge--warn{color:var(--state-warning-fg)}
.badge--warn .dot{background:var(--state-warning-fg)}
.badge--risk{color:var(--state-error-fg)}
.badge--risk .dot{background:var(--state-error-fg)}

.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:6px;
  height:26px;padding:0 var(--space-3);border-radius:var(--radius-md);
  border:1px solid var(--border-subtle-btm);border-top-color:var(--border-subtle-top);
  background:linear-gradient(180deg,var(--bg-surface-raised-top) 0%,
    var(--bg-surface-raised-btm) 100%);
  color:var(--text-primary);font-size:12px;font-weight:500;white-space:nowrap;
}
.btn:hover{background:linear-gradient(180deg,var(--accent-subtle),var(--accent-subtle)),
  linear-gradient(180deg,var(--bg-surface-raised-top) 0%,var(--bg-surface-raised-btm) 100%)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn--primary{
  background:linear-gradient(180deg,var(--accent-fill) 0%,var(--accent-fill-hover) 100%);
  border-color:var(--accent-fill-hover);color:var(--text-on-accent);
}
.btn--risk{border-color:var(--state-error-edge);color:var(--state-error-fg);background:none}

.listrow{display:flex;align-items:flex-start;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border-subtle-btm)}
.listrow:last-child{border-bottom:0}
.listrow__title{font-size:13px;font-weight:500}
.listrow__meta{font-size:11px;color:var(--text-tertiary)}
.listrow__snippet{font-size:12px;color:var(--text-secondary);margin-top:2px}

.diff{font-family:var(--font-mono);font-size:11px;line-height:1.5;color:var(--text-secondary);
  background:linear-gradient(180deg,var(--bg-surface-sunken-top) 0%,
    var(--bg-surface-sunken-btm) 100%);
  border-radius:var(--radius-sm);padding:var(--space-3);white-space:pre-wrap;word-break:break-word;
  max-height:220px;overflow:auto}

.empty{font-size:12px;color:var(--text-tertiary);padding:var(--space-4);text-align:center}
"""

#: Content-Security-Policy for the page's own ``<meta>`` tag — defense in
#: depth alongside the host-enforced CSP the tool's ``AppConfig`` carries
#: (:mod:`palaia_hub.gateway.apps`, no ``csp`` set there at all, which per
#: the MCP Apps extension is the strictest default: no external origin is
#: allowed to begin with). Every resource this page needs is already
#: inlined (fonts as ``data:`` URIs, the bridge script inline), so the
#: policy below denies network access entirely rather than allowlisting
#: anything.
_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "font-src data:; "
    "img-src data:; "
    "connect-src 'none'; "
    "frame-src 'none'; "
    "form-action 'none'"
)


def render_app_page(*, title: str, body_html: str, script_js: str) -> str:
    """Render one complete, self-contained MCP App page.

    ``body_html`` is the page's markup (already rendered — this function
    does no templating of its own beyond wrapping); ``script_js`` is the
    page-specific script, appended after the vendored bridge so it can
    reference ``window.McpAppLib`` directly. Neither is escaped — both are
    this codebase's own generated markup/script, not user input (a hostile
    note title reaching this page is escaped at the point it is
    interpolated into ``body_html``, in each app's own render function).
    """
    safe_title = html.escape(title)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">\n'
        f"<title>{safe_title}</title>\n"
        f"<style>{_fonts_css()}{LUME_CSS}</style>\n"
        "</head>\n"
        f"<body>\n{body_html}\n"
        f"<script>{_app_bridge_js()}</script>\n"
        f"<script>{script_js}</script>\n"
        "</body>\n"
        "</html>\n"
    )


__all__ = ["LUME_CSS", "render_app_page"]
