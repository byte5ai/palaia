"""The boot unit that starts palaia once its tailnet address is up (issue #614).

``get-palaia.sh`` publishes the hub on the server's tailnet address. When the
address is late at boot, Docker's start fails ("cannot assign requested
address") and Docker never retries it. The installer therefore writes
``/opt/palaia/start-on-tailnet.sh`` and a ``palaia-start-on-tailnet@.service``
unit that runs it. These tests run the shipped script, taken out of the
installer, against stand-ins for ``docker`` and ``ip``; the real thing is
checked with real reboots in a test VM.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[3] / "deploy" / "get-palaia.sh"

BIND_ERROR = (
    "failed to set up container networking: driver failed programming external "
    "connectivity on endpoint palaia (abc): failed to bind host port "
    "100.64.0.3:8420/tcp: cannot assign requested address"
)
BINDINGS = "100.64.0.3 127.0.0.1 127.0.0.1 "
ADDR_LINE = "3: tailscale0    inet 100.64.0.3/32 scope global tailscale0\\       valid_lft forever"
OTHER_LINES = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
    "2: enp5s0    inet 10.0.0.5/24 brd 10.0.0.255 scope global enp5s0\\       valid_lft forever\n"
)


def _installer() -> str:
    return INSTALLER.read_text(encoding="utf-8")


def _script() -> str:
    match = re.search(
        r"<<'PALAIA_START_ON_TAILNET'\n(.*?)^PALAIA_START_ON_TAILNET$", _installer(), re.S | re.M
    )
    assert match, "get-palaia.sh no longer writes start-on-tailnet.sh"
    return match.group(1)


def _unit() -> str:
    """The unit text exactly as the installer's printf produces it."""
    match = re.search(
        r"(printf '%s\\n' '\[Unit\]'.*?)\s*\|\s*"
        r"\$SUDO tee /etc/systemd/system/palaia-start-on-tailnet@\.service",
        _installer(),
        re.S,
    )
    assert match, "get-palaia.sh no longer writes palaia-start-on-tailnet@.service"
    result = subprocess.run(
        ["sh", "-c", match.group(1)], capture_output=True, text=True, timeout=10, check=True
    )
    return result.stdout


def _stub(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Lab:
    """Stand-ins for ``docker`` and ``ip`` whose answers live in files."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        state: str | None,
        address_after: int | None,
        attached: bool = True,
    ) -> None:
        self.dir = tmp_path
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.state = tmp_path / "state"
        if state is not None:
            self.state.write_text(state, encoding="utf-8")
        (tmp_path / "bindings").write_text(BINDINGS, encoding="utf-8")
        (tmp_path / "networks").write_text(
            '{"bridge":{"NetworkID":"abc"}}' if attached else "{}", encoding="utf-8"
        )
        self.starts = tmp_path / "starts"
        self.ip_calls = tmp_path / "ip_calls"
        self.ip_calls.write_text("0", encoding="utf-8")
        # `docker inspect` answers from the files. `docker network connect`
        # attaches the container; `docker start` is logged with whether it was
        # attached and how many times the address had been looked at, and
        # makes the container run.
        _stub(
            self.bin,
            "docker",
            f'D="{tmp_path}"\n'
            'case "$1" in\n'
            "  inspect)\n"
            '    [ -f "$D/state" ] || exit 1\n'
            '    case "$3" in\n'
            '      *PortBindings*) cat "$D/bindings" ;;\n'
            "      *NetworkMode*) echo bridge ;;\n"
            '      *Networks*) cat "$D/networks" ;;\n'
            '      *) cat "$D/state" ;;\n'
            "    esac ;;\n"
            "  network)\n"
            '    [ "$2 $3" = "connect bridge" ] || exit 2\n'
            '    echo "connect $3 $4" >> "$D/starts"\n'
            '    printf \'{"bridge":{"NetworkID":"abc"}}\' > "$D/networks" ;;\n'
            "  start)\n"
            '    grep -q \'"bridge"\' "$D/networks" && net=attached || net=detached\n'
            '    echo "start $2 ($net) after $(cat "$D/ip_calls") address checks" >> "$D/starts"\n'
            '    printf "true|" > "$D/state" ;;\n'
            "  *) exit 2 ;;\n"
            "esac\n",
        )
        # `ip -4 -o addr show`: the tailnet address shows up only from the
        # given call on (None: never).
        appear = "" if address_after is None else str(address_after)
        _stub(
            self.bin,
            "ip",
            f'D="{tmp_path}"\n'
            'n=$(( $(cat "$D/ip_calls") + 1 )); echo "$n" > "$D/ip_calls"\n'
            f"printf '%s' '{OTHER_LINES}'\n"
            f'[ -n "{appear}" ] && [ "$n" -ge "{appear or 0}" ] && echo \'{ADDR_LINE}\'\n'
            "exit 0\n",
        )
        self.script = tmp_path / "start-on-tailnet.sh"
        self.script.write_text(_script(), encoding="utf-8")

    def run(self, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(self.script), "palaia"],
            env={
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "PALAIA_START_INTERVAL": "0.05",
            },
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def started(self) -> list[str]:
        return self.starts.read_text(encoding="utf-8").splitlines() if self.starts.exists() else []


def test_a_start_that_failed_on_the_missing_address_is_repeated_once_it_is_up(
    tmp_path: Path,
) -> None:
    lab = Lab(tmp_path, state=f"false|{BIND_ERROR}", address_after=4)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    # Exactly one start, and only after the address appeared (4th look).
    assert lab.started() == ["start palaia (attached) after 4 address checks"]


def test_a_container_the_failed_start_detached_is_attached_again_before_starting(
    tmp_path: Path,
) -> None:
    """Docker 29 drops the container from its network when the start fails
    there; started as it is, it runs without its published ports."""
    lab = Lab(tmp_path, state=f"false|{BIND_ERROR}", address_after=2, attached=False)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    assert lab.started() == [
        "connect bridge palaia",
        "start palaia (attached) after 2 address checks",
    ]


def test_nothing_is_started_while_the_address_is_missing(tmp_path: Path) -> None:
    lab = Lab(tmp_path, state=f"false|{BIND_ERROR}", address_after=None)
    with pytest.raises(subprocess.TimeoutExpired):
        lab.run(timeout=1.5)
    assert lab.started() == []
    assert int(lab.ip_calls.read_text(encoding="utf-8")) > 1, "it stopped looking"


@pytest.mark.parametrize(
    ("state", "why"),
    [
        ("true|", "already running"),
        ("false|", "stopped on purpose (no start error)"),
        (
            "false|failed to bind host port 100.64.0.3:8420/tcp: address already in use",
            "failed for another reason",
        ),
    ],
)
def test_other_containers_states_are_left_alone(tmp_path: Path, state: str, why: str) -> None:
    lab = Lab(tmp_path, state=state, address_after=1)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    assert lab.started() == [], why


def test_no_container_means_nothing_to_do(tmp_path: Path) -> None:
    lab = Lab(tmp_path, state=None, address_after=1)
    result = lab.run()
    assert result.returncode == 0, result.stderr
    assert lab.started() == []


def test_the_unit_runs_the_script_after_docker_without_holding_anything_up() -> None:
    unit = _unit()
    lines = set(unit.splitlines())
    assert "ExecStart=/bin/sh /opt/palaia/start-on-tailnet.sh %i" in lines
    assert "After=docker.service tailscaled.service" in lines
    assert "WantedBy=multi-user.target" in lines
    # Type=simple: the boot (multi-user.target) does not wait for the address.
    assert "Type=simple" in lines
    # Never ordered before Docker: other containers start as usual.
    assert not any(line.startswith("Before=") for line in lines)
    # The script it runs is the one the installer writes.
    assert "tee /opt/palaia/start-on-tailnet.sh" in _installer()


def test_the_installer_enables_the_unit_for_its_container() -> None:
    assert (
        '$SUDO systemctl enable "palaia-start-on-tailnet@${CONTAINER_NAME}.service"' in _installer()
    )
