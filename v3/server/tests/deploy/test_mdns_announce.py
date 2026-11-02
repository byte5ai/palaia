"""``v3/deploy/mdns_announce.py``: which addresses ``palaia.local`` points at.

On the host network the container sees every interface of the machine. A
device that resolves ``palaia.local`` must get the LAN address, never a
Docker bridge, a veth or a tailnet address it cannot reach (issue #619).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

DEPLOY_ROOT = Path(__file__).resolve().parents[3] / "deploy"


def _load() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("mdns_announce", DEPLOY_ROOT / "mdns_announce.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mdns = _load()

#: A typical Linux box running Docker and Tailscale, on the host network.
HOST_NETWORK = [
    ("lo", "127.0.0.1"),
    ("enp3s0", "192.168.1.20"),
    ("docker0", "172.17.0.1"),
    ("br-3f2a9c1d7e11", "172.18.0.1"),
    ("veth1a2b3c", "169.254.10.3"),
    ("tailscale0", "100.101.102.103"),
]


def test_only_the_lan_address_is_advertised_on_the_host_network() -> None:
    assert mdns.select_lan_ipv4(HOST_NETWORK, "192.168.1.20") == ["192.168.1.20"]


def test_a_default_route_through_the_tailnet_does_not_hide_the_lan() -> None:
    # An exit node makes tailscale0 the default route; the LAN stays the answer.
    assert mdns.select_lan_ipv4(HOST_NETWORK, "100.101.102.103") == ["192.168.1.20"]


def test_wifi_and_ethernet_are_both_advertised_with_the_default_route_first() -> None:
    adapters = [("eth0", "192.168.1.20"), ("wlan0", "192.168.1.31"), ("docker0", "172.17.0.1")]
    assert mdns.select_lan_ipv4(adapters, "192.168.1.31") == ["192.168.1.31", "192.168.1.20"]


def test_a_carrier_grade_nat_address_is_never_the_lan() -> None:
    assert mdns.select_lan_ipv4([("eth0", "100.64.0.7")], "100.64.0.7") == []


def test_a_bridge_network_container_keeps_its_own_address() -> None:
    # Nothing outside sees it there; the log line and the README say so.
    assert mdns.select_lan_ipv4([("lo", "127.0.0.1"), ("eth0", "172.17.0.2")], "172.17.0.2") == [
        "172.17.0.2"
    ]


def test_no_address_yet_means_nothing_is_advertised() -> None:
    assert mdns.select_lan_ipv4([("lo", "127.0.0.1")], None) == []


class _FakeZeroconf:
    instances: list[_FakeZeroconf] = []

    def __init__(self, interfaces: list[str], ip_version: object) -> None:
        self.interfaces = interfaces
        self.registered: list[Any] = []
        self.closed = False
        _FakeZeroconf.instances.append(self)

    def register_service(self, info: Any) -> None:
        self.registered.append(info)

    def unregister_service(self, info: Any) -> None:
        self.registered.remove(info)

    def close(self) -> None:
        self.closed = True


class _FakeServiceInfo:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.addresses = kwargs["addresses"]
        self.server = kwargs["server"]


@pytest.fixture
def fake_zeroconf(monkeypatch: pytest.MonkeyPatch) -> type[_FakeZeroconf]:
    module = types.ModuleType("zeroconf")
    module.Zeroconf = _FakeZeroconf  # type: ignore[attr-defined]
    module.ServiceInfo = _FakeServiceInfo  # type: ignore[attr-defined]
    module.IPVersion = types.SimpleNamespace(V4Only="v4")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "zeroconf", module)
    _FakeZeroconf.instances = []
    return _FakeZeroconf


def test_a_new_address_replaces_the_old_registration(fake_zeroconf: type[_FakeZeroconf]) -> None:
    announcer = mdns.Announcer(8420)
    announcer.apply(["192.168.1.20"])
    announcer.apply(["192.168.1.20"])  # unchanged: nothing re-registered
    assert len(fake_zeroconf.instances) == 1
    first = fake_zeroconf.instances[0]
    assert first.interfaces == ["192.168.1.20"]
    assert first.registered[0].server == "palaia.local."

    announcer.apply(["192.168.1.44"])  # DHCP gave the box a new address
    assert first.closed and not first.registered
    second = fake_zeroconf.instances[1]
    assert second.interfaces == ["192.168.1.44"]
    assert second.registered[0].addresses == [bytes([192, 168, 1, 44])]


def test_losing_every_address_withdraws_the_announcement(
    fake_zeroconf: type[_FakeZeroconf],
) -> None:
    announcer = mdns.Announcer(8420)
    announcer.apply(["192.168.1.20"])
    announcer.apply([])
    assert fake_zeroconf.instances[0].closed
    assert len(fake_zeroconf.instances) == 1
