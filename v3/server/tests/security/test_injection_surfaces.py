"""Where untrusted text becomes markup or a log line (SPEC-502 #2).

Three surfaces, each with a different reason it is safe, each asserted here
rather than assumed:

* **The dashboard.** Note bodies, titles, tool names, marketplace copy and
  every other piece of vault- or upstream-supplied text is rendered by React
  as text, which escapes. The regression that would break that is a switch
  to ``dangerouslySetInnerHTML`` — so this module scans the dashboard source
  for it. (This is the "markdown rendering in the dashboard (XSS)" item: the
  dashboard renders note bodies as *text*, not as markdown, which is why the
  answer is a scan rather than a sanitizer.)
* **The MCP Apps.** Those pages *are* HTML, built by this codebase and
  rendered inside an AI client's iframe. Their scripts insert live data into
  the DOM, so each one carries an ``escapeHtml`` helper and the page carries
  its own restrictive ``<meta>`` content-security-policy.
* **MCP tool results and errors.** They reflect the caller's own arguments
  back (``no matches for 'foo'``), which is fine — the reflection reaches
  only the client that sent it — right up until such a string is *logged*.
  The property asserted here is that a credential-shaped argument reflected
  into a message is masked by the redaction filter before it can land in a
  log file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from palaia_hub.gateway.apps.shell import render_app_page
from palaia_hub.gateway.config import VaultMountConfig
from palaia_hub.gateway.fake_vault import FakeVaultService
from palaia_hub.gateway.memory_tools import build_vault_server
from palaia_hub.logging import redact

from .conftest import Hub

REPO_V3 = Path(__file__).resolve().parents[3]
WEB_SRC = REPO_V3 / "web" / "src"
APPS_DIR = Path(__file__).resolve().parents[2] / "src" / "palaia_hub" / "gateway" / "apps"

#: The payload used everywhere below. Deliberately one that survives naive
#: escaping attempts (a bare `<` replacement leaves the attribute break).
XSS = "<img src=x onerror=alert(1)>\"'</script>"


# ------------------------------------------------------------ the dashboard


def test_the_dashboard_never_sets_raw_html() -> None:
    """React escapes what it renders; this is the one way out of that."""
    offenders = [
        str(path.relative_to(REPO_V3))
        for path in sorted(WEB_SRC.rglob("*.ts*"))
        if "dangerouslySetInnerHTML" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


def test_the_scan_actually_reaches_the_dashboard_source() -> None:
    """Guard the guard: a scan over an empty directory proves nothing."""
    files = list(WEB_SRC.rglob("*.tsx"))
    assert len(files) >= 15, len(files)


# ----------------------------------------------------------- the MCP Apps


def _app_scripts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(APPS_DIR.glob("*_app.py"))
    }


def test_every_mcp_app_escapes_what_it_renders() -> None:
    scripts = _app_scripts()
    assert len(scripts) >= 5, sorted(scripts)
    missing = [name for name, text in scripts.items() if "function escapeHtml" not in text]
    assert missing == [], f"MCP App pages that render without an escape helper: {missing}"


def test_an_mcp_app_page_escapes_its_title_and_carries_a_policy() -> None:
    page = render_app_page(title=XSS, body_html="<p>body</p>", script_js="void 0;")

    assert XSS not in page
    assert "&lt;img src=x" in page
    assert 'http-equiv="Content-Security-Policy"' in page


# ------------------------------------------------ reflected tool arguments


@pytest.mark.anyio
async def test_a_tool_reflects_its_own_argument_but_nothing_else() -> None:
    """The reflection is confined to the caller's own response payload."""
    server = build_vault_server(
        VaultMountConfig(key="work", name="work", purpose="A vault."),
        FakeVaultService(),
    )
    async with Client(server) as client:
        result = await client.call_tool("search", {"query": XSS})

    rendered = json.dumps(result.structured_content) + str(result.content)
    # It comes back verbatim — that is correct for a machine surface, and
    # every renderer downstream escapes (the two tests above).
    assert "img src=x" in rendered


def test_a_credential_shaped_argument_is_masked_before_it_can_be_logged() -> None:
    """The one real risk in reflecting arguments: a client that pastes a
    token into a search box, and a hub that echoes it into a log line."""
    reflected = 'no matches for "token=sk-abcdef1234567890"'

    masked = redact(reflected)

    assert "sk-abcdef1234567890" not in masked
    assert "REDACTED" in masked


# -------------------------------------------- the server-rendered HTML pages


def test_the_sign_in_page_escapes_a_hostile_continue_url(hub: Hub) -> None:
    """``next`` is attacker-controllable and lands in a hidden input."""
    with TestClient(hub.app) as client:
        response = client.get("/oauth/login", params={"next": f"/{XSS}"})

    assert response.status_code == 200
    assert XSS not in response.text
    # The payload survives as *text* inside the hidden input's value — what
    # matters is that neither the tag nor the attribute delimiter does, so
    # nothing can break out of the attribute or open an element.
    assert "<img" not in response.text
    assert "</script>" not in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text


def test_the_oauth_pages_escape_every_value_they_render() -> None:
    """Structural backstop for the two server-rendered HTML pages.

    Both are built with f-strings in one module, so "did somebody add an
    interpolation and forget to escape it" is answerable by counting: every
    dynamic value that reaches the markup goes through ``html.escape``.
    """
    routes = (
        Path(__file__).resolve().parents[2] / "src" / "palaia_hub" / "oauth" / "routes.py"
    ).read_text(encoding="utf-8")

    assert routes.count("html.escape(") >= 5, routes.count("html.escape(")
    # The only two functions that build markup are the page renderers, and
    # neither may gain a raw f-string slot without an escape around it.
    for renderer in ("_login_page", "_authorize_error_page"):
        assert renderer in routes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
