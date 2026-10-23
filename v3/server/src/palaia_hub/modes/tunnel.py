"""Tunnel guidance for cloud access (SPEC-205 deliverable #2, issue #567).

Two providers, each pointed at one of the packaged image's two doors, chosen
by the hub's operating mode (MASTERPLAN §5.5's mode table):

- **cloud**: the tunnel forwards to the *cloud entry*
  (``deploy/nginx.conf.template``), which answers only the AI-connection
  routes — :data:`CLOUD_PUBLIC_PATH_PREFIXES` — and 404 for the dashboard and
  every ``/api`` route. The tunnel itself therefore needs no path list: the
  boundary lives in palaia, where a tunnel's configuration cannot get it
  wrong.
- **open**: the dashboard is deliberately public too, so the tunnel forwards
  to the whole hub.

Both targets are the loopback ports the installer publishes on the server
(``127.0.0.1:8422`` for the cloud entry, ``127.0.0.1:<install port>`` for the
whole hub) — Tailscale Funnel only proxies to localhost, and loopback keeps
both off every other interface. The hub reads the published port numbers
from the environment the installer sets; an operator with a different setup
passes ``local_port``.

Every function here is pure (a port/hostname in, guidance out), so the
golden tests can assert byte-for-byte output; nothing here touches a running
tunnel — see :mod:`palaia_hub.modes.detect` for whether either binary is
installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from .cloud_entry import CLOUD_ENTRY_PREFIXES

TunnelMode = Literal["cloud", "open"]

#: What the cloud entry lets through (see :mod:`palaia_hub.modes.cloud_entry`).
CLOUD_PUBLIC_PATH_PREFIXES: tuple[str, ...] = CLOUD_ENTRY_PREFIXES

#: The cloud entry's port on the server, as the installer publishes it.
CLOUD_HOST_PORT_ENV = "PALAIA_CLOUD_HOST_PORT"
DEFAULT_CLOUD_HOST_PORT = 8422
#: The whole hub's port on the server's loopback address ('open' mode).
HUB_HOST_PORT_ENV = "PALAIA_HUB_HOST_PORT"
DEFAULT_HUB_HOST_PORT = 8420


def default_local_port(mode: TunnelMode) -> int:
    """The server-side port a tunnel for ``mode`` should point at."""
    name, default = (
        (CLOUD_HOST_PORT_ENV, DEFAULT_CLOUD_HOST_PORT)
        if mode == "cloud"
        else (HUB_HOST_PORT_ENV, DEFAULT_HUB_HOST_PORT)
    )
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _scope(mode: TunnelMode) -> str:
    if mode != "cloud":
        return "the whole hub, including the dashboard"
    return "only palaia's AI connection (the dashboard and its API answer 404 there)"


@dataclass(frozen=True, slots=True)
class TunnelGuidance:
    """One tunnel setup, ready to copy."""

    #: e.g. "Tailscale Funnel", "cloudflared".
    label: str
    #: A configuration file to save first, or "" when the commands suffice.
    config: str
    #: The exact command(s) to run on the server.
    commands: tuple[str, ...]
    #: What this exposes, and what it deliberately does not.
    note: str


def tailscale_guidance(
    *,
    mode: TunnelMode,
    local_port: int,
    hostname: str = "<this server's tailnet name>",
) -> TunnelGuidance:
    """Tailscale Funnel: one command on the server, no configuration file."""
    target = f"http://127.0.0.1:{local_port}"
    return TunnelGuidance(
        label="Tailscale Funnel",
        config="",
        commands=(f"sudo tailscale funnel --bg {target}",),
        note=(
            f"Makes {_scope(mode)} reachable at https://{hostname}/. If Tailscale prints a "
            f"link, open it and allow Funnel for your tailnet, then run the command again. "
            f"'tailscale funnel status' shows what is shared."
        ),
    )


def cloudflared_guidance(
    *,
    mode: TunnelMode,
    local_port: int,
    hostname: str = "hub.example.com",
) -> TunnelGuidance:
    """cloudflared: an ``ingress`` config for ``cloudflared tunnel run``."""
    origin = f"http://127.0.0.1:{local_port}"
    config_text = (
        "tunnel: <your-tunnel-id>\n"
        "credentials-file: /etc/cloudflared/<your-tunnel-id>.json\n"
        "ingress:\n"
        f"  - hostname: {hostname}\n"
        f"    service: {origin}\n"
        "  - service: http_status:404\n"
    )
    return TunnelGuidance(
        label="cloudflared",
        config=config_text,
        commands=(
            "cloudflared tunnel create palaia-hub",
            "# save the printed tunnel id and credentials path into the config above",
            "cloudflared tunnel route dns palaia-hub " + hostname,
            "cloudflared tunnel run --config config.yml palaia-hub",
        ),
        note=(
            f"Makes {_scope(mode)} reachable at https://{hostname}/ once DNS and the tunnel are up."
        ),
    )


__all__ = [
    "CLOUD_PUBLIC_PATH_PREFIXES",
    "TunnelGuidance",
    "TunnelMode",
    "cloudflared_guidance",
    "default_local_port",
    "tailscale_guidance",
]
