"""Advertise the hub's dashboard as ``palaia.local`` over mDNS.

Best-effort and never fatal: if it can't announce — most commonly because
Docker's default bridge network doesn't forward multicast traffic to the
host's LAN — it logs why and returns normally. The container keeps serving
on its mapped port regardless; entrypoint.sh's startup log line (the actual
URL/port) is the always-available fallback, per SPEC-112's acceptance
criteria.

This is a deploy-only convenience script, not a hub feature: it lives here
rather than in ``palaia_hub`` so mDNS stays a packaging concern.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
import time

try:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
except ImportError:  # pragma: no cover - always installed in the runtime image
    print("mdns_announce: python-zeroconf not installed, skipping mDNS", file=sys.stderr)
    raise SystemExit(0)

HOSTNAME = "palaia.local."
SERVICE_TYPE = "_http._tcp.local."
SERVICE_NAME = "palaia hub._http._tcp.local."


def _local_ipv4() -> str | None:
    """Best-effort discovery of this container's routable IPv4 address."""
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8420)
    args = parser.parse_args()

    address = _local_ipv4()
    if address is None:
        print(
            "mdns_announce: could not determine a local IPv4 address; "
            "skipping mDNS (http://palaia.local will not resolve — use "
            "the printed host/port instead)",
            file=sys.stderr,
        )
        return

    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    info = ServiceInfo(
        SERVICE_TYPE,
        SERVICE_NAME,
        addresses=[socket.inet_aton(address)],
        port=args.port,
        server=HOSTNAME,
        properties={"path": "/"},
    )
    try:
        zeroconf.register_service(info)
    except Exception as exc:  # noqa: BLE001 - best-effort, must never crash the container
        print(
            f"mdns_announce: registration failed ({exc}); continuing without mDNS",
            file=sys.stderr,
        )
        zeroconf.close()
        return

    print(
        f"mdns_announce: advertising http://palaia.local:{args.port}/ "
        f"(container address {address}). On Linux this only reaches your "
        "LAN with `--network host` (or `network_mode: host` in compose) — "
        "see v3/deploy/README.md. Not supported on Docker Desktop "
        "(macOS/Windows).",
        file=sys.stderr,
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        zeroconf.unregister_service(info)
        zeroconf.close()


if __name__ == "__main__":
    main()
