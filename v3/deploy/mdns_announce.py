"""Advertise the hub's dashboard as ``palaia.local`` over mDNS.

Best-effort and never fatal: if it can't announce — most commonly because
Docker's default bridge network doesn't forward multicast traffic to the
host's LAN — it logs why and keeps the container serving on its port
regardless; entrypoint.sh's startup log line (the actual URL/port) is the
always-available fallback, per SPEC-112's acceptance criteria.

On the host network (the Linux ``docker run`` one-liner, compose, the Pi
image) the container sees every interface of the machine: the LAN, but also
Docker's own bridges and VPN links such as Tailscale. Only LAN addresses are
advertised, and only on those interfaces — a device that resolves
``palaia.local`` must get an address it can actually reach, never a Docker
bridge or a tailnet address (issue #619). The addresses are checked again
every half minute, so a box whose network comes up after the container, or
whose DHCP address changes, still ends up advertising the right one.

This is a deploy-only convenience script, not a hub feature: it lives here
rather than in ``palaia_hub`` so mDNS stays a packaging concern.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import socket
import sys
import time
from collections.abc import Iterable, Sequence

HOSTNAME = "palaia.local."
SERVICE_TYPE = "_http._tcp.local."
SERVICE_NAME = "palaia hub._http._tcp.local."

#: How often the advertised addresses are checked again, in seconds.
REFRESH_SECONDS = 30

#: Interface names that are never the LAN: container bridges and veths,
#: VPN and overlay links, virtual machine bridges.
_VIRTUAL_PREFIXES = (
    "docker",
    "br-",
    "veth",
    "virbr",
    "vnet",
    "lxc",
    "lxd",
    "incus",
    "podman",
    "cni",
    "flannel",
    "cali",
    "vxlan",
    "kube",
    "tailscale",
    "wg",
    "zt",
    "tun",
    "tap",
    "utun",
)

#: Address ranges that are never the LAN even on an ordinary-looking
#: interface: Tailscale and carrier-grade NAT (100.64.0.0/10).
_NON_LAN_NETWORKS = (ipaddress.ip_network("100.64.0.0/10"),)


def _is_lan_address(ip: str) -> bool:
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    if address.is_loopback or address.is_link_local or address.is_multicast:
        return False
    if address.is_unspecified or address.is_reserved:
        return False
    return not any(address in network for network in _NON_LAN_NETWORKS)


def _is_virtual_interface(name: str) -> bool:
    return name == "lo" or name.startswith(_VIRTUAL_PREFIXES)


def select_lan_ipv4(adapters: Iterable[tuple[str, str]], preferred: str | None) -> list[str]:
    """The LAN IPv4 addresses among ``(interface name, address)`` pairs.

    ``preferred`` — the address the default route leaves from — goes first
    when it is one of them. Inside a bridge-network container the only
    address is the container's own; it is returned as it is (nothing outside
    sees the announcement there anyway, and the log says so).
    """
    found: list[str] = []
    for name, ip in adapters:
        if _is_virtual_interface(name) or not _is_lan_address(ip) or ip in found:
            continue
        found.append(ip)
    if preferred in found:
        found.remove(preferred)
        found.insert(0, preferred)
    return found


def _default_route_ipv4() -> str | None:
    """The address this machine reaches the internet from (no packet is sent)."""
    with contextlib.suppress(OSError):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return str(sock.getsockname()[0])
    return None


def _adapters() -> list[tuple[str, str]]:
    """Every ``(interface name, IPv4 address)`` of this network namespace."""
    try:
        import ifaddr  # noqa: PLC0415 - installed with python-zeroconf in the image
    except ImportError:  # pragma: no cover - always installed in the runtime image
        return []
    pairs: list[tuple[str, str]] = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str):
                pairs.append((str(adapter.nice_name), ip.ip))
    return pairs


def current_addresses() -> list[str]:
    return select_lan_ipv4(_adapters(), _default_route_ipv4())


def _log(message: str) -> None:
    print(f"mdns_announce: {message}", file=sys.stderr, flush=True)


class Announcer:
    """Keeps one registration of ``palaia.local`` matching ``addresses``."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.addresses: list[str] = []
        self._zeroconf: object | None = None
        self._info: object | None = None

    def apply(self, addresses: Sequence[str]) -> None:
        if list(addresses) == self.addresses:
            return
        self.stop()
        self.addresses = list(addresses)
        if not self.addresses:
            return
        from zeroconf import IPVersion, ServiceInfo, Zeroconf  # noqa: PLC0415

        zeroconf = Zeroconf(interfaces=self.addresses, ip_version=IPVersion.V4Only)
        info = ServiceInfo(
            SERVICE_TYPE,
            SERVICE_NAME,
            addresses=[socket.inet_aton(address) for address in self.addresses],
            port=self.port,
            server=HOSTNAME,
            properties={"path": "/"},
        )
        try:
            zeroconf.register_service(info)
        except Exception as exc:  # noqa: BLE001 - best-effort, must never crash the container
            _log(f"registration failed ({exc}); trying again in {REFRESH_SECONDS} s")
            zeroconf.close()
            self.addresses = []
            return
        self._zeroconf, self._info = zeroconf, info
        _log(
            f"advertising http://palaia.local:{self.port}/ at {', '.join(self.addresses)}. "
            "This reaches your local network only when the container runs on the host "
            "network (Linux) — see v3/deploy/README.md. Not possible on Docker Desktop "
            "(macOS/Windows)."
        )

    def stop(self) -> None:
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = self._info = None
        if zeroconf is None:
            return
        with contextlib.suppress(Exception):
            zeroconf.unregister_service(info)  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            zeroconf.close()  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8420)
    args = parser.parse_args()

    try:
        import zeroconf  # noqa: F401, PLC0415
    except ImportError:  # pragma: no cover - always installed in the runtime image
        _log("python-zeroconf not installed, skipping mDNS")
        return

    announcer = Announcer(args.port)
    waiting_logged = False
    try:
        while True:
            addresses = current_addresses()
            if not addresses and not waiting_logged:
                _log(
                    "no local network address yet; palaia.local is not advertised until one "
                    "appears (use the printed host/port meanwhile)"
                )
                waiting_logged = True
            elif addresses:
                waiting_logged = False
            announcer.apply(addresses)
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        announcer.stop()


if __name__ == "__main__":
    main()
