"""Issue #400: the packaged nginx sets the dashboard's browser headers on
the static locations only — a server-level `add_header` inherits into the
proxy location, which declares none, so API/MCP/OAuth responses carried the
dashboard policy a second time."""

from __future__ import annotations

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf.template"


def _blocks() -> tuple[str, dict[str, str]]:
    """(server-level text outside any location, {location header: body})."""
    text = TEMPLATE.read_text(encoding="utf-8")
    server = text[text.index("server {") :]
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
