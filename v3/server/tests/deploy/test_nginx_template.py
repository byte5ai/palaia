"""Issue #400: the packaged nginx sets the dashboard's browser headers on
the static locations only — a server-level `add_header` inherits into the
proxy location, which declares none, so API/MCP/OAuth responses carried the
dashboard policy a second time."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf.template"


def _blocks() -> tuple[str, dict[str, str]]:
    """(server-level text outside any location, {location header: body})."""
    text = TEMPLATE.read_text(encoding="utf-8")
    server = text[text.index("server {") : text.index("listen ${CLOUD_LISTEN};")]
    locations: dict[str, str] = {}
    outside = []
    depth = 0
    current: list[str] | None = None
    header = ""
    for line in server.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # comments may mention directives without setting them
        if current is None and stripped.startswith("location "):
            header = stripped.rstrip("{").strip()
            current = []
            depth = 1
            continue
        if current is not None:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0:
                locations[header] = "\n".join(current)
                current = None
                continue
            current.append(line)
        else:
            outside.append(line)
    return "\n".join(outside), locations


def test_no_browser_header_is_set_at_server_level() -> None:
    outside, _ = _blocks()
    assert "add_header" not in outside


def test_the_proxy_location_declares_no_browser_headers() -> None:
    _, locations = _blocks()
    proxy = next(body for header, body in locations.items() if "api|mcp" in header)
    assert "add_header" not in proxy
    assert "client_max_body_size" in proxy


def test_both_static_locations_carry_the_dashboard_policy() -> None:
    _, locations = _blocks()
    for header in ("location /", "location = /index.html"):
        body = locations[header]
        assert re.search(r'add_header Content-Security-Policy ".*frame-ancestors \'none\'', body)
        assert 'add_header X-Frame-Options "DENY" always;' in body


def _proxied_prefix_pattern() -> re.Pattern[str]:
    """The proxy location's own regex, compiled as written in the template.

    nginx matches ``location ~`` with PCRE; this regex uses nothing PCRE and
    Python disagree on, so the template's literal is the thing under test —
    not a second copy of it kept in this file."""
    _, locations = _blocks()
    header = next(header for header in locations if "api|mcp" in header)
    return re.compile(header.split("~", 1)[1].strip())


@pytest.mark.parametrize(
    "path",
    [
        "/api/health",
        "/mcp/default/",
        "/oauth/token",
        "/.well-known/oauth-authorization-server",
        # Issue #439: Telegram's webhook deliveries reach the hub, not the SPA.
        "/telegram/webhook/support",
        "/telegram/webhook",
    ],
)
def test_every_backend_prefix_is_proxied_to_the_hub(path: str) -> None:
    assert _proxied_prefix_pattern().search(path), path


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/assets/app.js",
        "/telegramx",
        "/explorer/telegram",
        # Issue #570: `/telegram` is an old dashboard address that redirects
        # to Settings › Telegram; the hub has no route there.
        "/telegram",
        "/telegram/",
        "/settings/telegram",
    ],
)
def test_the_dashboard_stays_with_the_static_locations(path: str) -> None:
    assert not _proxied_prefix_pattern().search(path), path


def test_the_proxy_forwards_the_host_header_with_its_port() -> None:
    """``$host`` drops the port; the hub builds redirects and the Claude
    Desktop bundle's address from this header."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "proxy_set_header Host $http_host;" in text
    assert "proxy_set_header Host $host;" not in text


def _directives(text: str) -> list[str]:
    """Directive lines, comments dropped (they may mention directives)."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_nginx_own_redirects_on_the_private_door_stay_relative() -> None:
    """Issue #620: a browser that reached the hub on port 80 (the Pi image's
    redirect, the tailnet's `tailscale serve --http=80`) must never be sent
    to `:8420` by a redirect nginx makes itself — with `absolute_redirect`
    on (nginx's default), the Location names this listener's port."""
    outside, _ = _blocks()
    assert "absolute_redirect off;" in _directives(outside)


def test_the_template_issues_no_redirect_that_needs_an_absolute_location() -> None:
    """`absolute_redirect off` only stays harmless while nothing in the
    template builds its own redirect target. The hub's redirects pass through
    the proxy unchanged (only a Location starting with the `proxy_pass` URL is
    rewritten, `proxy_redirect default`)."""
    directives = _directives(TEMPLATE.read_text(encoding="utf-8"))
    assert not [d for d in directives if re.match(r"return\s+30[12378]\b", d)]
    assert not [d for d in directives if d.startswith("rewrite ")]
    assert not [d for d in directives if d.startswith("proxy_redirect ")]


def _forwarded_proto_map() -> dict[str, str]:
    """The `map` that picks the private door's `X-Forwarded-Proto`, as written."""
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"map \$http_x_forwarded_proto \$(\w+) \{([^}]*)\}", text)
    assert match, "the private door no longer maps X-Forwarded-Proto"
    _, locations = _blocks()
    private = next(body for header, body in locations.items() if "api|mcp" in header)
    assert f"proxy_set_header X-Forwarded-Proto ${match.group(1)};" in private
    entries = (line.strip().rstrip(";").split() for line in match.group(2).splitlines())
    return {entry[0]: entry[1] for entry in entries if len(entry) == 2}


def _forwarded_proto(sent: str | None, scheme: str = "http") -> str:
    """What the hub sees behind the private door, the way nginx's `map` picks it."""
    table = _forwarded_proto_map()
    value = table.get(sent or "", table["default"])
    return scheme if value == "$scheme" else value


def test_a_tls_tunnel_in_front_of_the_private_door_keeps_https() -> None:
    """Open mode: a tunnel terminates TLS and forwards to port 8420 over http.
    The hub must still learn the browser used https, or its sign-in cookies
    lose `Secure` on the public address."""
    assert _forwarded_proto("https") == "https"


@pytest.mark.parametrize("sent", [None, "http", "ftp"])
def test_a_plain_http_visit_on_the_private_door_stays_http(sent: str | None) -> None:
    """The dashboard over the owner's own network: cookies without `Secure`,
    which a browser keeps on plain http (issue #561)."""
    assert _forwarded_proto(sent) == "http"


# ------------------------------------------------ the cloud entry (#566, #567)


def _cloud_block() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    return text[text.index("listen ${CLOUD_LISTEN};") :]


def _cloud_pattern() -> re.Pattern[str]:
    match = re.search(r"location ~ (\S+) \{", _cloud_block())
    assert match, "the cloud entry lost its location"
    return re.compile(match.group(1))


@pytest.mark.parametrize(
    "path",
    [
        "/mcp/default/",
        "/oauth/authorize",
        "/oauth/login",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/mcp/default",
        "/telegram/webhook/support",
    ],
)
def test_the_cloud_entry_forwards_the_ai_connection(path: str) -> None:
    assert _cloud_pattern().match(path)


@pytest.mark.parametrize(
    "path", ["/", "/index.html", "/assets/app.js", "/api/info", "/api/mode", "/telegram", "/mcpx"]
)
def test_the_cloud_entry_never_forwards_the_dashboard_or_admin_api(path: str) -> None:
    assert not _cloud_pattern().match(path)
    assert 'return 404 "Not found.' in _cloud_block()


def test_the_cloud_entry_marks_its_requests_and_the_private_door_clears_the_mark() -> None:
    cloud = _cloud_block()
    assert "proxy_set_header X-Palaia-Entry cloud;" in cloud
    assert "proxy_set_header X-Forwarded-Proto https;" in cloud
    _, locations = _blocks()
    private = next(body for header, body in locations.items() if "api|mcp" in header)
    assert 'proxy_set_header X-Palaia-Entry "";' in private


def test_the_cloud_entry_and_the_hub_agree_on_the_routes() -> None:
    from palaia_hub.modes.cloud_entry import CLOUD_ENTRY_PREFIXES

    alternatives = _cloud_pattern().pattern.split("(", 1)[1].split(")", 1)[0].split("|")
    assert {"/" + alt.replace("\\.", ".") for alt in alternatives} == set(CLOUD_ENTRY_PREFIXES)


def test_the_cloud_entry_tells_the_hub_who_is_calling() -> None:
    """Every request at the cloud entry comes from the local tunnel through
    Docker's bridge: without the real address from X-Forwarded-For, all public
    callers would share one failed-sign-in bucket and one caller could lock
    everyone out. Only local hops are trusted; the private door trusts none."""
    cloud = _cloud_block()
    assert "real_ip_header X-Forwarded-For;" in cloud
    assert "real_ip_recursive on;" in cloud
    trusted = set(re.findall(r"set_real_ip_from (\S+);", cloud))
    assert trusted == {"127.0.0.0/8", "::1", "172.16.0.0/12"}
    text = TEMPLATE.read_text(encoding="utf-8")
    private = text[: text.index("listen ${CLOUD_LISTEN};")]
    assert "set_real_ip_from" not in private


ENTRYPOINT = TEMPLATE.parent / "entrypoint.sh"


def _listen_address(env: dict[str, str]) -> str:
    """CLOUD_LISTEN as entrypoint.sh's own defaults block computes it."""
    text = ENTRYPOINT.read_text(encoding="utf-8")
    block = text[text.index(': "${PUBLIC_PORT:=8420}"') : text.index("export PUBLIC_PORT")]
    result = subprocess.run(  # noqa: S603 - fixed argv, the script's own text
        ["bash", "-c", f'set -eu\n{block}\nprintf %s "$CLOUD_LISTEN"'],  # noqa: S607
        env={"PATH": "/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_the_cloud_entry_listens_on_every_container_address_by_default() -> None:
    # Docker's bridge network: only the loopback port the installer and
    # compose publish reaches it.
    assert _listen_address({}) == "8422"


def test_on_the_host_network_the_cloud_entry_listens_on_loopback_only() -> None:
    # Issue #619: the host-network commands set PALAIA_CLOUD_BIND, so the
    # local network never reaches the cloud entry directly.
    assert _listen_address({"PALAIA_CLOUD_BIND": "127.0.0.1"}) == "127.0.0.1:8422"
    assert _listen_address({"PALAIA_CLOUD_BIND": "127.0.0.1", "CLOUD_PORT": "9422"}) == (
        "127.0.0.1:9422"
    )


def test_every_template_variable_is_rendered_by_the_entrypoint() -> None:
    used = set(re.findall(r"\$\{([A-Z_]+)\}", TEMPLATE.read_text(encoding="utf-8")))
    rendered_line = next(
        line for line in ENTRYPOINT.read_text(encoding="utf-8").splitlines() if "envsubst" in line
    )
    assert used == set(re.findall(r"\$\{([A-Z_]+)\}", rendered_line))
