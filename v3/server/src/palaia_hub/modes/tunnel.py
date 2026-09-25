"""Tunnel configs for the exposure wizard (SPEC-205 deliverable #2).

Two providers, each with two flavors, chosen by the hub's own operating
mode (MASTERPLAN §5.5's mode table):

- **cloud**: only the MCP surface and its own auth doorway need to be
  public — the admin dashboard stays VPN/tailnet-only *even when a tunnel
  makes the box reachable from the internet*, so the tunnel config only
  forwards :data:`CLOUD_PUBLIC_PATH_PREFIXES` (the gateway, the OAuth
  authorize/login/token endpoints a remote browser must reach to sign in,
  and the ``.well-known`` discovery documents every client probes first).
- **open**: the dashboard is deliberately public too, so the tunnel
  forwards everything.

One conditional addition to the 'cloud' list (issue #439): a hub with a
Telegram bot on ``transport: webhook`` also needs Telegram's servers to reach
:data:`TELEGRAM_WEBHOOK_PATH_PREFIX`, so the caller passes
``telegram_webhook=True`` and the route joins the forwarded prefixes. Only
then — a hub with no webhook bot gets byte-for-byte the config it always
did, and does not put a route on the internet that nothing uses.

Every function here is pure (a port/hostname in, a config out) so the
golden-file test (this SPEC's acceptance criterion #3) can assert byte-for-
byte output, and so generating a config never touches the filesystem or a
running tunnel — this module never shells out to ``tailscale``/
``cloudflared``; see :mod:`palaia_hub.modes.detect` for whether either
binary is even installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

TunnelMode = Literal["cloud", "open"]

#: Path prefixes that must stay reachable through a 'cloud'-mode tunnel:
#: the MCP gateway itself, the OAuth doorway a remote browser is redirected
#: through to sign in, and the discovery documents every client probes
#: before either. Everything else (the dashboard, the REST admin API) is
#: deliberately left off this list — MASTERPLAN §5.5's mode table keeps the
#: dashboard VPN/tailnet-only in 'cloud' mode even once MCP is public.
CLOUD_PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/mcp", "/oauth", "/.well-known")

#: The Telegram connector's webhook route (issue #439), forwarded in 'cloud'
#: mode only when a webhook bot is configured. Its own credential is
#: Telegram's secret-token header, checked by the hub. Kept as a literal so
#: this module stays a pure generator with nothing heavier than ``json``
#: behind it (importing :mod:`palaia_hub.telegram.webhook` drags FastAPI
#: in); ``tests/modes/test_tunnel.py`` asserts the two agree.
TELEGRAM_WEBHOOK_PATH_PREFIX = "/telegram/webhook"


def _public_prefixes(mode: TunnelMode, *, telegram_webhook: bool = False) -> tuple[str, ...]:
    if mode != "cloud":
        return ("/",)
    if telegram_webhook:
        return (*CLOUD_PUBLIC_PATH_PREFIXES, TELEGRAM_WEBHOOK_PATH_PREFIX)
    return CLOUD_PUBLIC_PATH_PREFIXES


def _scope(mode: TunnelMode, *, telegram_webhook: bool = False) -> str:
    """What the generated config exposes, for the guidance note."""
    if mode != "cloud":
        return "the whole hub, including the dashboard"
    if telegram_webhook:
        return "only the MCP endpoint, its sign-in pages and the Telegram webhook"
    return "only the MCP endpoint and its sign-in pages"


@dataclass(frozen=True, slots=True)
class TunnelGuidance:
    """One generated tunnel config, ready to copy-paste."""

    #: e.g. "tailscale serve (JSON config)", "cloudflared (ingress YAML)".
    label: str
    #: The config text itself.
    config: str
    #: The exact command(s) that apply/run it.
    commands: tuple[str, ...]
    #: Plain-language note — what this exposes, and what it deliberately
    #: does not (the dashboard, in 'cloud' mode).
    note: str


def tailscale_guidance(
    *,
    mode: TunnelMode,
    local_port: int,
    hostname: str = "<your-tailnet-name>",
    telegram_webhook: bool = False,
) -> TunnelGuidance:
    """Tailscale Serve/Funnel guidance: a ``tailscale serve --set-raw`` JSON config.

    Serve makes the hostname reachable on the tailnet; Funnel (a second,
    explicit command — Tailscale never exposes a serve config to the
    public internet without it) additionally opens it to the public
    internet, which is what 'cloud'/'open' mode actually needs.

    ``telegram_webhook``: forward the Telegram webhook route too, in 'cloud'
    mode (see the module docstring). No effect in 'open' mode, which already
    forwards everything.
    """
    origin = f"http://127.0.0.1:{local_port}"
    handlers = {
        prefix: {"Proxy": origin}
        for prefix in _public_prefixes(mode, telegram_webhook=telegram_webhook)
    }
    raw_config = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{hostname}:443": {"Handlers": handlers}},
        "AllowFunnel": {f"{hostname}:443": True},
    }
    config_text = json.dumps(raw_config, indent=2) + "\n"
    scope = _scope(mode, telegram_webhook=telegram_webhook)
    return TunnelGuidance(
        label="Tailscale Serve + Funnel",
        config=config_text,
        commands=(
            'tailscale serve --set-raw "$(cat tailscale-serve.json)"',
            "tailscale funnel 443 on",
        ),
        note=(
            f"Exposes {scope} at https://{hostname}/ — "
            f"'tailscale funnel 443 on' is what makes it reachable from "
            f"the public internet, not just your tailnet; run "
            f"'tailscale funnel status' to confirm."
        ),
    )


def cloudflared_guidance(
    *,
    mode: TunnelMode,
    local_port: int,
    hostname: str = "hub.example.com",
    telegram_webhook: bool = False,
) -> TunnelGuidance:
    """cloudflared guidance: an ``ingress`` config for ``cloudflared tunnel run``.

    ``telegram_webhook``: as for :func:`tailscale_guidance`.
    """
    origin = f"http://127.0.0.1:{local_port}"
    prefixes = _public_prefixes(mode, telegram_webhook=telegram_webhook)
    lines = [
        "tunnel: <your-tunnel-id>",
        "credentials-file: /etc/cloudflared/<your-tunnel-id>.json",
        "ingress:",
    ]
    if prefixes == ("/",):
        lines.append(f"  - hostname: {hostname}")
        lines.append(f"    service: {origin}")
    else:
        for prefix in prefixes:
            lines.append(f"  - hostname: {hostname}")
            lines.append(f"    path: ^{prefix}")
            lines.append(f"    service: {origin}")
    lines.append("  - service: http_status:404")
    config_text = "\n".join(lines) + "\n"
    scope = _scope(mode, telegram_webhook=telegram_webhook)
    return TunnelGuidance(
        label="cloudflared (ingress rules)",
        config=config_text,
        commands=(
            "cloudflared tunnel create palaia-hub",
            "# save the printed tunnel id and credentials path into the ingress config above",
            "cloudflared tunnel route dns palaia-hub " + hostname,
            "cloudflared tunnel run --config config.yml palaia-hub",
        ),
        note=f"Exposes {scope} at https://{hostname}/ once DNS + the tunnel are both up.",
    )


__all__ = [
    "CLOUD_PUBLIC_PATH_PREFIXES",
    "TELEGRAM_WEBHOOK_PATH_PREFIX",
    "TunnelGuidance",
    "TunnelMode",
    "cloudflared_guidance",
    "tailscale_guidance",
]
