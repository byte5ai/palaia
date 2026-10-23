"""The shared MCP App shell: one self-contained HTML page builder.

SPEC-208 deliverable #1. Every app this package serves (hub status, recall
explorer, review queue) is rendered by :func:`render_app_page`, which
produces one complete, self-contained ``<!doctype html>`` document:

- **The design system's tokens** (:data:`COLORS`, from
  ``v3/design/tokens.json``, the one source the dashboard and the docs site
  are generated from — ``server/tests/gateway/test_apps_shell.py`` keeps the
  values equal) plus a small set of components (card, status pill, button,
  list row, input) these compact panels actually use. An MCP App is one
  panel inside a chat, not a whole application with a sidebar.
- **One self-hosted font file** (:func:`_fonts_css`), Nunito Sans, embedded
  as a ``data:`` URI from the same WOFF2 file the dashboard self-hosts
  (``v3/web/src/assets/fonts``, vendored into this package under
  ``vendor/fonts`` so the server wheel does not depend on the ``web/``
  package at runtime). Only the upright latin cut: these are compact UI
  panels; code and numbers use the system's monospace font.
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
    nunito = _font_data_uri("nunito-sans-normal-latin.woff2")
    return f"""
@font-face {{
  font-family: 'Nunito Sans';
  font-style: normal;
  font-weight: 200 1000;
  font-display: swap;
  src: url('{nunito}') format('woff2');
}}
"""


#: The design system's colours, ``name: (light, dark)`` — the same values
#: as ``v3/design/tokens.json`` (a test keeps them equal).
COLORS: dict[str, tuple[str, str]] = {
    "canvas": ("#F5F7FA", "#0F1520"),
    "surface": ("#FFFFFF", "#161D2A"),
    "surface-muted": ("#EEF1F5", "#1C2433"),
    "border": ("#E3E7ED", "#263043"),
    "text": ("#1D232C", "#E8ECF1"),
    "text-2": ("#4B5563", "#AEB6C2"),
    "text-3": ("#667080", "#8B95A3"),
    "action": ("#0369A1", "#38BDF8"),
    "action-hover": ("#04618F", "#7DD3FC"),
    "on-action": ("#FFFFFF", "#0A0F1A"),
    "focus": ("#0369A1", "#009FE3"),
    "ok": ("#157A3A", "#4ADE80"),
    "ok-bg": ("#E8F2EB", "#1E3C38"),
    "warn": ("#8A5A0A", "#FACC15"),
    "warn-bg": ("#F3EEE6", "#3A3927"),
    "error": ("#B91C1C", "#F87171"),
    "error-bg": ("#F8E8E8", "#3A2A35"),
    "neutral-bg": ("#EDEEEF", "#2E3542"),
}


def _color_vars(index: int) -> str:
    return "".join(f"--{name}:{values[index]};" for name, values in COLORS.items())


_LIGHT = _color_vars(0) + "--shadow-card:0 1px 2px rgba(15,21,32,.06);"
_DARK = _color_vars(1) + "--shadow-card:none;"

#: Light tokens on bare ``:root``; dark tokens both under
#: ``prefers-color-scheme: dark`` (no explicit host choice) and under
#: ``:root[data-theme="dark"]`` (an explicit host choice wins), the
#: theme-aware pattern every self-contained page in this codebase follows.
APP_CSS = (
    ":root{color-scheme:light dark;"
    "--space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:20px;"
    "--radius-sm:10px;--radius-md:14px;--radius-pill:999px;"
    "--font-sans:'Nunito Sans',system-ui,-apple-system,'Segoe UI',sans-serif;"
    "--font-mono:ui-monospace,'SF Mono','Cascadia Code',Menlo,Consolas,monospace;"
    + _LIGHT
    + "}\n"
    + '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){'
    + _DARK
    + "}}\n"
    + ':root[data-theme="dark"]{'
    + _DARK
    + "}\n"
    + """
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--canvas);color:var(--text);
  font-family:var(--font-sans);font-size:14px;line-height:20px;
  padding:var(--space-4);
}
h1,h2,h3,p{margin:0}
button,input{font:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.t-mono{font-family:var(--font-mono);font-size:13px;font-variant-numeric:tabular-nums}
.t-muted{color:var(--text-2)}
.t-subtle{color:var(--text-3)}
.t-sm{font-size:13px;line-height:20px}
.t-xs{font-size:12px;line-height:16px}
.t-over{font-size:12px;line-height:16px;font-weight:600;color:var(--text-3)}
.stack{display:flex;flex-direction:column;gap:var(--space-4)}
.stack--2{display:flex;flex-direction:column;gap:var(--space-2)}
.row{display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap}
.row--between{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3)}

.card{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius-md);box-shadow:var(--shadow-card)}
.card__head{display:flex;align-items:center;justify-content:space-between;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border)}
.card__title{font-size:15px;line-height:22px;font-weight:600;color:var(--text)}
.card__body{padding:var(--space-4)}

.tile{background:var(--surface-muted);border-radius:var(--radius-sm);
  padding:var(--space-3) var(--space-4);display:flex;flex-direction:column;gap:var(--space-1)}
.tile__metric{font-size:20px;line-height:28px;font-weight:700;font-variant-numeric:tabular-nums}
.tile__label{font-size:12px;line-height:16px;font-weight:600;color:var(--text-3)}

.badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;
  border-radius:var(--radius-pill);background:var(--neutral-bg);color:var(--text-2);
  font-size:12px;line-height:18px;font-weight:600;white-space:nowrap}
.badge .dot{width:6px;height:6px;border-radius:50%;background:currentColor;flex:none}
.badge--ok{background:var(--ok-bg);color:var(--ok)}
.badge--warn{background:var(--warn-bg);color:var(--warn)}
.badge--risk{background:var(--error-bg);color:var(--error)}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;
  min-height:32px;padding:0 var(--space-4);border-radius:var(--radius-pill);
  border:1px solid var(--border);background:var(--surface);color:var(--text);
  font-size:13px;font-weight:600;white-space:nowrap}
.btn:hover{background:var(--surface-muted)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.btn--primary{background:var(--action);border-color:var(--action);color:var(--on-action)}
.btn--primary:hover{background:var(--action-hover);border-color:var(--action-hover)}
.btn--risk{color:var(--error)}

.input{width:100%;min-height:36px;padding:0 var(--space-3);border:1px solid var(--border);
  border-radius:var(--radius-sm);background:var(--surface);color:var(--text)}
.field__error{color:var(--error);font-size:13px}

.listrow{display:flex;align-items:flex-start;gap:var(--space-3);
  padding:var(--space-3) var(--space-4);border-bottom:1px solid var(--border)}
.listrow:last-child{border-bottom:0}
.listrow__title{font-size:14px;line-height:20px;font-weight:600}
.listrow__meta{font-size:12px;line-height:16px;color:var(--text-3)}
.listrow__snippet{font-size:13px;line-height:20px;color:var(--text-2);margin-top:2px}

.diff{font-family:var(--font-mono);font-size:12px;line-height:18px;color:var(--text-2);
  background:var(--surface-muted);border-radius:var(--radius-sm);padding:var(--space-3);
  white-space:pre-wrap;word-break:break-word;max-height:220px;overflow:auto}

.empty{font-size:13px;color:var(--text-2);padding:var(--space-4);text-align:center}
"""
)

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
        f"<style>{_fonts_css()}{APP_CSS}</style>\n"
        "</head>\n"
        f"<body>\n{body_html}\n"
        f"<script>{_app_bridge_js()}</script>\n"
        f"<script>{script_js}</script>\n"
        "</body>\n"
        "</html>\n"
    )


__all__ = ["APP_CSS", "COLORS", "render_app_page"]
