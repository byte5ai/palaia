"""Pieces of ``v3/deploy/get-palaia.sh`` run for real in ``sh``.

The installer as a whole needs root, Docker and Tailscale and is exercised on
a real server; these tests take single functions out of the shipped file and
run them against stand-ins, so the logic itself is checked, not its text.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy" / "get-palaia.sh"


def _function(name: str) -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, f"get-palaia.sh no longer defines {name}()"
    return match.group(0)


def _run(body: str, env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "-c", body],
        env={"PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}", **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _stub(tmp_path: Path, name: str, script: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    path = bindir / name
    path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_cleanup_removes_a_key_the_caller_cannot_see_without_sudo(tmp_path: Path) -> None:
    """Run by a sudo user, the key lives under /root, which that user cannot
    search: an existence test without sudo says "missing" and keeps it."""
    hidden = tmp_path / "root"
    hidden.mkdir()
    key = hidden / ".palaia-tskey"
    key.write_text("tskey-auth-synthetic", encoding="utf-8")
    hidden.chmod(0)
    # "sudo" here: grant access for the one command, as the real one would.
    _stub(
        tmp_path,
        "fakesudo",
        f'chmod 700 "{hidden}"\n"$@"\nstatus=$?\nchmod 0 "{hidden}"\nexit $status\n',
    )
    try:
        result = _run(
            _function("cleanup") + "cleanup\n",
            {"SUDO": "fakesudo", "KEYFILE": str(key), "UFW_OPENED": "0"},
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
    finally:
        hidden.chmod(0o700)
    assert not key.exists()


HELPERS = (
    'log()  { echo "palaia: $*"; }\n'
    'err()  { echo "palaia: ERROR: $*" >&2; }\n'
    'die()  { err "$@"; exit 1; }\n'
)
TS_HINT = "Installation complete! Log in to start using Tailscale by running:\n\ntailscale up\n"


def _tailscale_install(
    tmp_path: Path, script: str, *, download_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run install_tailscale() with `curl` handing back ``script`` as
    Tailscale's installer (or failing to download it)."""
    source = tmp_path / "ts-install.sh"
    source.write_text(script, encoding="utf-8")
    fetch = (
        f'while [ "$#" -gt 0 ]; do [ "$1" = "-o" ] && out="$2"; shift; done\ncp "{source}" "$out"\n'
    )
    _stub(tmp_path, "curl", fetch if download_ok else "exit 22\n")
    # Only the tools the function needs, so a `tailscale` on the machine
    # running the tests cannot stand in for the one the install must leave.
    tools = tmp_path / "tools"
    tools.mkdir()
    for tool in ("sh", "mktemp", "rm", "cp", "cat", "tail", "sed", "mkdir", "chmod", "printf"):
        found = shutil.which(tool)
        assert found, f"{tool} is needed to run this test"
        (tools / tool).symlink_to(found)
    return subprocess.run(
        ["sh", "-c", HELPERS + _function("install_tailscale") + "install_tailscale\necho after\n"],
        env={"PATH": f"{tmp_path / 'bin'}{os.pathsep}{tools}", "SUDO": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_tailscale_install_keeps_its_login_hint_off_the_screen(tmp_path: Path) -> None:
    """Tailscale's "run tailscale up" hint contradicts the setup page (#616)."""
    tailscale = tmp_path / "bin" / "tailscale"
    result = _tailscale_install(
        tmp_path,
        f"printf '#!/bin/sh\\n' > '{tailscale}'; chmod +x '{tailscale}'\n"
        "echo 'Installing Tailscale for ubuntu noble, using method apt'\n"
        f"printf '%s' '{TS_HINT}'\n",
    )
    assert result.returncode == 0, result.stderr
    assert "tailscale up" not in result.stdout + result.stderr
    assert "Installation complete" not in result.stdout + result.stderr
    assert result.stdout.strip().endswith("after")


def test_a_failed_tailscale_install_shows_its_error(tmp_path: Path) -> None:
    result = _tailscale_install(
        tmp_path,
        "echo 'Installing Tailscale'\necho 'E: Unable to locate package tailscale'\nexit 100\n",
    )
    assert result.returncode != 0
    assert "E: Unable to locate package tailscale" in result.stderr
    assert "installing Tailscale failed" in result.stderr
    assert "after" not in result.stdout


def test_a_tailscale_install_that_leaves_no_tailscale_is_a_failure(tmp_path: Path) -> None:
    """Exit 0 is not enough: the installer needs the `tailscale` command."""
    result = _tailscale_install(tmp_path, "echo 'Unsupported, nothing installed'\nexit 0\n")
    assert result.returncode != 0
    assert "Unsupported, nothing installed" in result.stderr
    assert "after" not in result.stdout


def test_a_failed_download_of_tailscales_installer_stops_the_install(tmp_path: Path) -> None:
    result = _tailscale_install(tmp_path, "", download_ok=False)
    assert result.returncode != 0
    assert "could not download Tailscale's installer" in result.stderr
    assert "after" not in result.stdout


UFW_ACTIVE = (
    "Status: active\n\n"
    "To                         Action      From\n"
    "--                         ------      ----\n"
)


@pytest.mark.parametrize(
    ("rules", "allowed"),
    [
        ("8420/tcp                   ALLOW       Anywhere\n", True),
        ("8420                       ALLOW IN    Anywhere\n", True),
        ("8420/tcp on tailscale0     ALLOW       Anywhere\n", False),
        ("8420/tcp                   ALLOW       203.0.113.7\n", False),
        ("8420/tcp                   DENY        Anywhere\n", False),
        ("18420/tcp                  ALLOW       Anywhere\n", False),
        ("OpenSSH                    ALLOW       Anywhere\n", False),
    ],
)
def test_only_a_rule_for_everyone_counts_as_open(tmp_path: Path, rules: str, allowed: bool) -> None:
    """A tailnet-only rule left by an earlier run, or one for a single source,
    must not stop the installer from opening the setup page's port."""
    (tmp_path / "status.txt").write_text(UFW_ACTIVE + rules, encoding="utf-8")
    _stub(tmp_path, "ufw", f'cat "{tmp_path / "status.txt"}"\n')
    result = _run(
        _function("ufw_allows_everyone") + 'ufw_allows_everyone "$PORT"\n',
        {"SUDO": "", "PORT": "8420"},
        tmp_path,
    )
    assert (result.returncode == 0) is allowed, result.stderr


def _ss(tmp_path: Path, listeners: list[str]) -> None:
    """`ss -Hltn` standing in: one LISTEN line per local address given."""
    lines = "".join(f"LISTEN 0      4096   {local}   0.0.0.0:*\n" for local in listeners)
    (tmp_path / "ss.txt").write_text(lines, encoding="utf-8")
    _stub(tmp_path, "ss", f'cat "{tmp_path / "ss.txt"}"\n')


def _choose_port80(tmp_path: Path, listeners: list[str], bind: str) -> tuple[str, str]:
    _ss(tmp_path, listeners)
    result = _run(
        _function("port80_free")
        + _function("choose_port80")
        + 'choose_port80\necho "publish=$HTTP_PUBLISH"\necho "port80=$PORT80"\n',
        {"SUDO": "", "BIND_ADDR": bind, "PORT": "8420"},
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    out = dict(line.split("=", 1) for line in result.stdout.splitlines())
    return out["publish"], out["port80"]


@pytest.mark.parametrize(
    ("listeners", "published"),
    [
        ([], True),
        (["127.0.0.1:80"], True),  # another single address: no conflict
        (["100.64.0.70:80"], True),  # a different address that merely starts the same
        (["100.64.0.7:8420", "0.0.0.0:22"], True),  # other ports
        (["0.0.0.0:80"], False),
        (["*:80"], False),
        (["[::]:80"], False),
        (["100.64.0.7:80"], False),
        (["127.0.0.1:80", "[::]:80"], False),
    ],
)
def test_port_80_is_published_on_the_tailnet_address_only_when_free(
    tmp_path: Path, listeners: list[str], published: bool
) -> None:
    """#620: port 80 of the tailnet address goes straight to the container, so
    each caller keeps its own address (per-device sign-in limits); but never
    over a program that already listens there."""
    publish, port80 = _choose_port80(tmp_path, listeners, "100.64.0.7")
    if published:
        assert (publish, port80) == ("-p 100.64.0.7:80:8420", "1")
    else:
        assert (publish, port80) == ("", "0")


def test_without_tailscale_port_80_is_never_published(tmp_path: Path) -> None:
    """PALAIA_NO_TAILSCALE=1 binds 0.0.0.0; that path stays as it is."""
    assert _choose_port80(tmp_path, [], "0.0.0.0") == ("", "0")


def test_before_the_join_only_listeners_on_every_address_count(tmp_path: Path) -> None:
    """The setup page runs before the tailnet address exists."""
    script = _function("port80_free") + 'port80_free ""\n'
    _ss(tmp_path, ["127.0.0.1:80", "192.0.2.5:80"])
    assert _run(script, {"SUDO": ""}, tmp_path).returncode == 0
    _ss(tmp_path, ["0.0.0.0:80"])
    assert _run(script, {"SUDO": ""}, tmp_path).returncode != 0


def test_the_hub_is_published_with_the_port_80_choice(tmp_path: Path) -> None:
    """The container really gets the publish chosen above (and the boot unit
    later restarts that same container, so it stays)."""
    _stub(tmp_path, "docker", f'echo "$*" >> "{tmp_path / "docker.log"}"\n')
    result = _start_hub(tmp_path, "-p 100.64.0.7:80:8420")
    assert result.returncode == 0, result.stderr
    calls = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1
    assert "-p 100.64.0.7:8420:8420 -p 100.64.0.7:80:8420 -p 127.0.0.1:8420:8420" in calls[0]


HUB_ENV = {
    "SUDO": "",
    "DOCKER": "docker",
    "CONTAINER_NAME": "palaia",
    "BIND_ADDR": "100.64.0.7",
    "PORT": "8420",
    "CLOUD_PORT": "8422",
    "CLOUD_URL": "",
    "VOLUME": "palaia_home",
    "IMAGE": "ghcr.io/byte5ai/palaia:beta",
    "LOOPBACK_PUBLISH": "-p 127.0.0.1:8420:8420",
}


def _start_hub(tmp_path: Path, http_publish: str) -> subprocess.CompletedProcess[str]:
    return _run(
        HELPERS
        + _function("run_hub")
        + _function("start_hub")
        + 'start_hub\nstatus=$?\necho "port80=$PORT80 publish=$HTTP_PUBLISH"\nexit $status\n',
        {**HUB_ENV, "HTTP_PUBLISH": http_publish, "PORT80": "1" if http_publish else "0"},
        tmp_path,
    )


def _docker_failing_on(tmp_path: Path, message: str) -> None:
    """`docker run` fails with ``message`` while the port-80 publish is in its arguments."""
    _stub(
        tmp_path,
        "docker",
        f'echo "$*" >> "{tmp_path / "docker.log"}"\n'
        'case "$1 $*" in\n'
        f'  run*"-p 100.64.0.7:80:8420"*) echo "{message}" >&2; exit 125 ;;\n'
        "esac\n",
    )


def test_a_port_80_taken_since_the_check_is_retried_without_it(tmp_path: Path) -> None:
    _docker_failing_on(
        tmp_path,
        "docker: Error response from daemon: driver failed programming external "
        "connectivity on endpoint palaia: Bind for 100.64.0.7:80 failed: "
        "port is already allocated.",
    )
    result = _start_hub(tmp_path, "-p 100.64.0.7:80:8420")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "port80=0 publish="
    calls = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert [call.split()[0] for call in calls] == ["run", "rm", "run"]
    assert "100.64.0.7:80:8420" in calls[0]
    assert calls[1] == "rm -f palaia"
    assert ":80:8420" not in calls[2]


def test_another_start_failure_is_not_retried(tmp_path: Path) -> None:
    _docker_failing_on(tmp_path, "docker: Error response from daemon: no space left on device.")
    result = _start_hub(tmp_path, "-p 100.64.0.7:80:8420")
    assert result.returncode != 0
    assert "no space left on device" in result.stderr
    calls = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1


def _report_address(
    tmp_path: Path, answer: str, bind: str = "100.64.0.7", port80: str = "1"
) -> list[str]:
    """Run report_address() with `python3` standing in for setup-page.py."""
    (tmp_path / "answer.txt").write_text(answer, encoding="utf-8")
    _stub(
        tmp_path,
        "python3",
        f'echo "$*" > "{tmp_path / "args.txt"}"\ncat "{tmp_path / "answer.txt"}"\n',
    )
    result = _run(
        HELPERS + _function("report_address") + "report_address\n",
        {
            "SUDO": "",
            "BIND_ADDR": bind,
            "PORT": "8420",
            "PORT80": port80,
            "URL": f"http://{bind}:8420/",
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


DONE = "palaia: done ✓  Open {} from any device on your tailnet to finish setup."


@pytest.mark.parametrize("port80", ["1", "0"])
def test_the_last_line_names_palaia_instead_of_its_number(tmp_path: Path, port80: str) -> None:
    """#619/#620: the installer's last line is what the person opens, and the
    first sign-in is tied to it — the name, and the full name next to it. The
    address step is told whether port 80 was really published."""
    lines = _report_address(
        tmp_path,
        "address=http://palaia/\nfull_address=http://palaia.tail1234.ts.net/\naddress_note=\n",
        port80=port80,
    )
    assert lines == [
        DONE.format("http://palaia/"),
        "palaia:   full name: http://palaia.tail1234.ts.net/",
    ]
    args = (tmp_path / "args.txt").read_text(encoding="utf-8").split()
    assert args == ["/opt/palaia/setup-page.py", "address", "--port", "8420", "--port-80", port80]


def test_without_magicdns_the_last_line_keeps_the_number_and_says_why(tmp_path: Path) -> None:
    note = "Your Tailscale network has MagicDNS turned off, so palaia has no name there."
    lines = _report_address(
        tmp_path, f"address=http://100.64.0.7:8420/\nfull_address=\naddress_note={note}\n"
    )
    assert lines == [DONE.format("http://100.64.0.7:8420/"), f"palaia:   {note}"]


def test_no_answer_keeps_the_address_the_installer_had(tmp_path: Path) -> None:
    assert _report_address(tmp_path, "") == [DONE.format("http://100.64.0.7:8420/")]


def test_without_tailscale_nothing_asks_tailscale(tmp_path: Path) -> None:
    """PALAIA_NO_TAILSCALE=1 binds 0.0.0.0 and has no setup page to ask."""
    lines = _report_address(tmp_path, "address=http://palaia/\n", bind="0.0.0.0")
    assert lines == [DONE.format("http://0.0.0.0:8420/")]
    assert not (tmp_path / "args.txt").exists()


def test_a_new_server_joins_the_tailnet_as_palaia() -> None:
    """One name, `palaia` (#619): the tailnet name people type (`http://palaia/`)
    and the container's name.

    Both the key path (the installer's own `tailscale up`) and the setup page
    (its `--hostname` default, which the installer passes through) use it.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    for line in (
        'HOSTNAME_TS="${PALAIA_TS_HOSTNAME:-palaia}"',
        'CONTAINER_NAME="${PALAIA_CONTAINER_NAME:-palaia}"',
    ):
        assert re.search(rf"^{re.escape(line)}$", text, re.MULTILINE), line
    assert 'parser.add_argument("--hostname", default="palaia")' in text
    page = (SCRIPT.parent / "setup-page.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--hostname", default="palaia")' in page


# --- #621: each tailnet device keeps its own address -------------------------


def _source_settings() -> str:
    """The installer's own SOURCE_* lines, so the tests use its paths and names."""
    lines = re.findall(r"^SOURCE_[A-Z_]+=.*$", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert lines, "get-palaia.sh no longer sets SOURCE_RULES and friends"
    return "\n".join(lines) + "\n"


def _keep_tailnet_source(
    tmp_path: Path, *, bind: str, http_publish: str, nft: bool = True, load_ok: bool = True
) -> subprocess.CompletedProcess[str]:
    """keep_tailnet_source() with stand-ins for systemctl, nft and apt-get, on
    a PATH without the machine's own tools, under paths inside tmp_path."""
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for tool in ("sh", "cat", "tee", "mkdir", "dirname", "rm"):
        found = shutil.which(tool)
        assert found, f"{tool} is needed to run this test"
        if not (tools / tool).exists():
            (tools / tool).symlink_to(found)
    calls = tmp_path / "calls.log"
    _stub(
        tmp_path,
        "systemctl",
        f'echo "systemctl $*" >> "{calls}"\n'
        + ("" if load_ok else '[ "$1" = restart ] && exit 1\n'),
    )
    _stub(tmp_path, "apt-get", f'echo "apt-get $*" >> "{calls}"\nexit 100\n')
    if nft:
        _stub(tmp_path, "nft", f'echo "nft $*" >> "{calls}"\n')
    (tmp_path / "systemd").mkdir(exist_ok=True)
    paths = (
        f'SOURCE_RULES="{tmp_path}/opt/tailnet-source-palaia.nft"\n'
        f'SOURCE_UNIT_FILE="{tmp_path}/systemd/palaia-tailnet-source@.service"\n'
    )
    return subprocess.run(
        [
            "sh",
            "-c",
            HELPERS
            + 'CONTAINER_NAME="palaia"\n'
            + _source_settings()
            + paths
            + _function("tailnet_source_rules")
            + _function("tailnet_source_unit")
            + _function("keep_tailnet_source")
            + "keep_tailnet_source\necho after\n",
        ],
        env={
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{tools}",
            "SUDO": "",
            "BIND_ADDR": bind,
            "PORT": "8420",
            "HTTP_PUBLISH": http_publish,
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "calls.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.parametrize(
    ("http_publish", "ports"),
    [("-p 100.64.0.7:80:8420", "{ 8420, 80 }"), ("", "{ 8420 }")],
)
def test_the_tailnet_rule_covers_exactly_the_ports_palaia_publishes(
    tmp_path: Path, http_publish: str, ports: str
) -> None:
    """Port 80 only when palaia has it: another program's port 80 is not ours
    to change."""
    result = _keep_tailnet_source(tmp_path, bind="100.64.0.7", http_publish=http_publish)
    assert result.returncode == 0, result.stderr
    rules = (tmp_path / "opt" / "tailnet-source-palaia.nft").read_text(encoding="utf-8")
    rule = next(line for line in rules.splitlines() if "meta mark set" in line)
    assert "ct original ip daddr 100.64.0.7 " in rule
    assert f"ct original proto-dst {ports} " in rule


def test_the_tailnet_rule_is_loaded_now_and_at_every_boot(tmp_path: Path) -> None:
    result = _keep_tailnet_source(tmp_path, bind="100.64.0.7", http_publish="")
    assert result.returncode == 0, result.stderr
    assert "WARNING" not in result.stdout
    # restart, not start: a re-run must load the file it just rewrote.
    assert _calls(tmp_path) == [
        "systemctl daemon-reload",
        "systemctl enable palaia-tailnet-source@palaia.service",
        "systemctl restart palaia-tailnet-source@palaia.service",
    ]
    unit = (tmp_path / "systemd" / "palaia-tailnet-source@.service").read_text(encoding="utf-8")
    assert "WantedBy=multi-user.target" in unit


def test_the_boot_unit_loads_and_removes_what_the_installer_writes(tmp_path: Path) -> None:
    """The unit names the file and the table through %i; both must be the ones
    the installer uses for this container."""
    result = _run(
        HELPERS
        + 'CONTAINER_NAME="palaia"\n'
        + _source_settings()
        + _function("tailnet_source_unit")
        + "tailnet_source_unit /usr/sbin/nft\n"
        + 'echo "rules=$SOURCE_RULES"\necho "table=$SOURCE_TABLE"\n',
        {},
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.replace("%i", "palaia")
    rules = re.search(r"^rules=(.*)$", out, re.M)
    table = re.search(r"^table=(.*)$", out, re.M)
    assert rules and table
    assert f"ExecStart=/usr/sbin/nft -f {rules.group(1)}\n" in out
    assert f"ExecStop=/usr/sbin/nft delete table {table.group(1)}\n" in out
    assert "Type=oneshot\nRemainAfterExit=yes\n" in out


def test_without_nft_the_install_goes_on_and_says_what_is_missing(tmp_path: Path) -> None:
    result = _keep_tailnet_source(tmp_path, bind="100.64.0.7", http_publish="", nft=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("after")
    assert "apt-get install -y nftables" in _calls(tmp_path)
    assert "WARNING: nft is not available" in result.stdout
    assert not (tmp_path / "opt").exists()


def test_a_rule_that_does_not_load_is_reported(tmp_path: Path) -> None:
    result = _keep_tailnet_source(tmp_path, bind="100.64.0.7", http_publish="", load_ok=False)
    assert result.returncode == 0, result.stderr
    assert "WARNING: could not load" in result.stdout
    assert result.stdout.strip().endswith("after")


def test_off_the_tailnet_a_rule_from_an_earlier_install_goes(tmp_path: Path) -> None:
    """PALAIA_NO_TAILSCALE=1 after a tailnet install: nothing of #621 stays."""
    (tmp_path / "opt").mkdir()
    (tmp_path / "opt" / "tailnet-source-palaia.nft").write_text("old\n", encoding="utf-8")
    result = _keep_tailnet_source(tmp_path, bind="0.0.0.0", http_publish="")
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "opt" / "tailnet-source-palaia.nft").exists()
    assert _calls(tmp_path) == [
        "systemctl disable --now palaia-tailnet-source@palaia.service",
        "nft delete table ip palaia_source_palaia",
    ]


def test_without_tailscale_and_no_earlier_rule_nothing_is_touched(tmp_path: Path) -> None:
    result = _keep_tailnet_source(tmp_path, bind="0.0.0.0", http_publish="")
    assert result.returncode == 0, result.stderr
    assert _calls(tmp_path) == []
    assert not (tmp_path / "opt").exists()


# --- #646: the install runs on its own, apart from the session that started it


LAUNCH_TOOLS = (
    "sh", "cat", "tr", "grep", "sleep", "tail", "mkdir", "mv", "rm", "chmod",
    "dirname", "sed", "setsid", "touch", "printf",
)  # fmt: skip


def _launcher(tmp_path: Path) -> str:
    """get-palaia.sh's launcher part (everything before the install text),
    with its files under ``tmp_path``."""
    text = SCRIPT.read_text(encoding="utf-8")
    runner = re.search(r"^INSTALL_RUNNER='.*?'$", text, re.S | re.M)
    variables = re.search(r'^INSTALL_VARS=".*?"$', text, re.S | re.M)
    assert runner and variables, "get-palaia.sh no longer sets INSTALL_RUNNER and INSTALL_VARS"
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    paths = (
        f'INSTALLER_FILE="{tmp_path}/opt/installer.sh"\n'
        f'INSTALL_LOG="{tmp_path}/install.log"\n'
        f'INSTALL_ENV="{run}/palaia-install.env"\n'
        f'INSTALL_PID="{run}/palaia-install.pid"\n'
        f'INSTALL_STATUS="{run}/palaia-install.status"\n'
        'INSTALL_UNIT="palaia-install"\n'
    )
    functions = "".join(
        _function(name)
        for name in (
            "launch_options",
            "launch_running",
            "launch_claim",
            "launch_start",
            "launch_follow",
            "launch_drop_keyfile",
            "launch_abort",
            "launch",
        )
    )
    return (
        "set -eu\n"
        + HELPERS
        + 'SUDO=""\n'
        + paths
        + runner.group(0)
        + "\n"
        + variables.group(0)
        + "\n"
        + "LAUNCHED=0\nCLAIMED=0\n"
        + functions
        + 'launch < "$PAYLOAD"\n'
    )


def _launch_env(tmp_path: Path, payload: Path, *, systemd_run: bool) -> dict[str, str]:
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    for tool in LAUNCH_TOOLS:
        found = shutil.which(tool)
        if found is None:
            pytest.skip(f"{tool} is needed to run this test")
        if not (tools / tool).exists():
            (tools / tool).symlink_to(found)
    if systemd_run:
        # Stands in for systemd-run: records the call, then runs the command
        # after the options the way the service would — apart, with no
        # terminal, and with systemd's expansion of its command line ($$ is
        # a $, $NAME and ${NAME} the variable's value: empty here).
        runner = tmp_path / "systemd-run.py"
        calls = str(tmp_path / "systemd-run.log")
        runner.write_text(
            "import os, re, sys\n"
            f"open({calls!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "args = sys.argv[sys.argv.index('/bin/sh'):]\n"
            "expand = lambda a: re.sub(r'\\$(\\$|\\{\\w+\\}|\\w+)',"
            " lambda m: '$' if m.group(1) == '$' else '', a)\n"
            "if os.fork() == 0:\n"
            "    os.setsid()\n"
            "    fd = os.open(os.devnull, os.O_RDWR)\n"
            "    for n in (0, 1, 2): os.dup2(fd, n)\n"
            "    os.execvp(args[0], [expand(a) for a in args])\n",
            encoding="utf-8",
        )
        _stub(tmp_path, "systemd-run", f'exec "{sys.executable}" "{runner}" "$@"\n')
    (tmp_path / "bin").mkdir(exist_ok=True)
    return {"PATH": f"{tmp_path / 'bin'}{os.pathsep}{tools}", "PAYLOAD": str(payload)}


def _payload(tmp_path: Path, body: str, name: str = "payload.sh", *, complete: bool = True) -> Path:
    path = tmp_path / name
    path.write_text(
        "#!/bin/sh\n" + body + ("# palaia installer: end\n" if complete else ""), encoding="utf-8"
    )
    return path


TICKING = (
    'echo "install started, code=${PALAIA_SETUP_CODE:-none}"\n'
    "i=0\n"
    'while [ "$i" -lt 40 ]; do echo "step $i"; i=$((i + 1)); sleep 0.05; done\n'
    'echo "palaia: done ✓  Open http://palaia/ from any device on your tailnet to finish setup."\n'
    "exit ${PAYLOAD_EXIT:-0}\n"
)


def _wait_for(path: Path, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.05)


@pytest.mark.parametrize("systemd_run", [False, True])
def test_the_install_finishes_after_the_session_that_started_it_is_gone(
    tmp_path: Path, systemd_run: bool
) -> None:
    """#646: `ssh server 'curl … | sh'` ends (timeout, dropped connection):
    its output pipe closes. The install goes on to its end, its log has every
    line, and its status is kept for whoever looks next."""
    if systemd_run and not Path("/run/systemd/system").is_dir():
        pytest.skip("the systemd-run path is taken only where systemd runs")
    payload = _payload(tmp_path, TICKING)
    env = {**_launch_env(tmp_path, payload, systemd_run=systemd_run)}
    env["PALAIA_SETUP_CODE"] = "ABCD-EFGH-JKLM"
    proc = subprocess.Popen(
        ["sh", "-c", _launcher(tmp_path)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    seen = ""
    while "step 1" not in seen:
        line = proc.stdout.readline()
        assert line, f"the command ended before the install showed progress: {seen!r}"
        seen += line
    assert "the install runs on its own now" in seen
    proc.stdout.close()  # the session is gone
    proc.wait(timeout=30)

    status = tmp_path / "run" / "palaia-install.status"
    _wait_for(status)
    assert status.read_text(encoding="utf-8").strip() == "0"
    log = (tmp_path / "install.log").read_text(encoding="utf-8")
    assert "install started, code=ABCD-EFGH-JKLM" in log
    assert "step 39" in log
    assert "palaia: done ✓  Open http://palaia/" in log
    assert stat.S_IMODE((tmp_path / "install.log").stat().st_mode) == 0o600
    # Nothing is left running, and the options file is gone.
    assert not (tmp_path / "run" / "palaia-install.pid").exists()
    assert not (tmp_path / "run" / "palaia-install.env").exists()
    if systemd_run:
        call = (tmp_path / "systemd-run.log").read_text(encoding="utf-8")
        assert "--unit=palaia-install" in call
        assert "--collect" in call
        assert "ABCD-EFGH-JKLM" not in call  # options never on a command line


def test_while_it_runs_the_command_shows_the_progress_and_ends_with_it(tmp_path: Path) -> None:
    payload = _payload(tmp_path, TICKING)
    env = {**_launch_env(tmp_path, payload, systemd_run=False), "PAYLOAD_EXIT": "0"}
    result = subprocess.run(
        ["sh", "-c", _launcher(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert "step 39" in lines
    assert lines[-1].startswith("palaia: done ✓  Open")


def test_its_exit_status_is_the_commands(tmp_path: Path) -> None:
    payload = _payload(tmp_path, 'echo "palaia: ERROR: something failed" >&2\nexit 1\n')
    result = subprocess.run(
        ["sh", "-c", _launcher(tmp_path)],
        env=_launch_env(tmp_path, payload, systemd_run=False),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "palaia: ERROR: something failed" in result.stdout


def test_a_second_command_shows_the_running_install_instead_of_starting_one(
    tmp_path: Path,
) -> None:
    """#646: a rerun while an install runs attaches to it: no second install,
    no traceback, no "run again" — and a key file given to it is not left
    behind."""
    first = _payload(tmp_path, TICKING.replace("sleep 0.05", "sleep 0.1"), "first.sh")
    env = {**_launch_env(tmp_path, first, systemd_run=False), "PAYLOAD_EXIT": "3"}
    started = subprocess.Popen(
        ["sh", "-c", _launcher(tmp_path)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pidfile = tmp_path / "run" / "palaia-install.pid"
    deadline = time.monotonic() + 20
    while not (pidfile.exists() and pidfile.read_text(encoding="utf-8").strip().isdigit()):
        assert time.monotonic() < deadline, "the first install never started"
        time.sleep(0.05)

    second = _payload(tmp_path, f'touch "{tmp_path / "second-ran"}"\n', "second.sh")
    key = tmp_path / "tskey"
    key.write_text("tskey-auth-synthetic", encoding="utf-8")
    result = subprocess.run(
        ["sh", "-c", _launcher(tmp_path)],
        env={**env, "PAYLOAD": str(second), "PALAIA_TSKEY_FILE": str(key)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    started.wait(timeout=30)
    assert "still running" in result.stdout
    assert "install started" in result.stdout  # its progress from the start
    assert "step 39" in result.stdout
    assert result.returncode == 3  # the running install's own result
    assert not (tmp_path / "second-ran").exists()
    assert "second-ran" not in (tmp_path / "opt" / "installer.sh").read_text(encoding="utf-8")
    assert not key.exists()


def test_after_an_install_ended_the_command_starts_a_new_one(tmp_path: Path) -> None:
    once = _payload(tmp_path, f'echo run >> "{tmp_path / "runs"}"\n')
    env = _launch_env(tmp_path, once, systemd_run=False)
    for _ in range(2):
        result = subprocess.run(
            ["sh", "-c", _launcher(tmp_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "runs").read_text(encoding="utf-8") == "run\nrun\n"


def test_a_pid_file_left_by_a_killed_install_does_not_block_the_next(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    gone = subprocess.Popen(["true"])
    gone.wait()
    (tmp_path / "run" / "palaia-install.pid").write_text(f"{gone.pid}\n", encoding="utf-8")
    once = _payload(tmp_path, f'touch "{tmp_path / "ran"}"\n')
    result = subprocess.run(
        ["sh", "-c", _launcher(tmp_path)],
        env=_launch_env(tmp_path, once, systemd_run=False),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "ran").exists()


def test_an_install_that_arrived_cut_short_never_runs(tmp_path: Path) -> None:
    cut = _payload(tmp_path, f'touch "{tmp_path / "ran"}"\n', complete=False)
    key = tmp_path / "tskey"
    key.write_text("tskey-auth-synthetic", encoding="utf-8")
    env = {**_launch_env(tmp_path, cut, systemd_run=False), "PALAIA_TSKEY_FILE": str(key)}
    result = subprocess.run(
        ["sh", "-c", _launcher(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "did not arrive complete" in result.stderr
    assert not (tmp_path / "ran").exists()
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == []
    assert not key.exists()


def test_the_options_reach_the_install_unchanged(tmp_path: Path) -> None:
    tricky = 'it\'s $HOME "quoted" `x` \\ end'
    payload = _payload(
        tmp_path,
        'printf "%s\\n" "$PALAIA_TS_LOGIN_SERVER" > "$OUT"\n'
        'printf "%s\\n" "${PALAIA_CLOUD-unset}" >> "$OUT"\n',
    )
    out = tmp_path / "seen"
    env = {
        **_launch_env(tmp_path, payload, systemd_run=False),
        "PALAIA_TS_LOGIN_SERVER": tricky,
    }
    script = _launcher(tmp_path).replace("set -eu\n", f'set -eu\nOUT="{out}"\n', 1)
    # OUT reaches the install only through the options file, like PALAIA_*.
    script = script.replace('INSTALL_VARS="', 'INSTALL_VARS="OUT ', 1)
    result = subprocess.run(
        ["sh", "-c", script], env=env, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert out.read_text(encoding="utf-8") == f"{tricky}\nunset\n"


def _strip_heredocs(text: str) -> str:
    """The install's own text, without the files it writes (their variables
    are read by those files, not by the install)."""
    return re.sub(r"<<'([A-Z_]+)'\n.*?^\1$", "", text, flags=re.S | re.M)


def test_every_option_the_install_reads_is_passed_on() -> None:
    """The install runs in a service of its own: an option it reads but the
    command does not pass on would silently do nothing."""
    text = SCRIPT.read_text(encoding="utf-8")
    install = re.search(r"<<'PALAIA_INSTALLER'\n(.*?)^PALAIA_INSTALLER$", text, re.S | re.M)
    assert install, "get-palaia.sh no longer carries the install between PALAIA_INSTALLER lines"
    read = set(re.findall(r"\$\{(PALAIA_[A-Z_]+)", _strip_heredocs(install.group(1))))
    variables = re.search(r'^INSTALL_VARS="(.*?)"$', text, re.S | re.M)
    assert variables
    assert read == set(variables.group(1).split())


def test_the_install_text_ends_with_the_line_the_command_checks() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    install = re.search(r"<<'PALAIA_INSTALLER'\n(.*?)^PALAIA_INSTALLER$", text, re.S | re.M)
    assert install
    last = install.group(1).rstrip("\n").splitlines()[-1]
    assert f'!= "{last}" ]' in _function("launch")


def test_a_closed_output_pipe_still_removes_the_key_file(tmp_path: Path) -> None:
    """#646: dash ends on a closed pipe without running its EXIT trap; the
    install's own PIPE trap runs the clean-up."""
    text = SCRIPT.read_text(encoding="utf-8")
    traps = re.findall(r"^trap .*$", text.split("<<'PALAIA_INSTALLER'", 1)[1], re.M)
    assert traps
    key = tmp_path / "tskey"
    key.write_text("tskey-auth-synthetic", encoding="utf-8")
    script = (
        HELPERS
        + 'SUDO=""\n'
        + _function("cleanup")
        + "\n".join(traps)
        + "\nwhile :; do echo still here; sleep 0.05; done\n"
    )
    proc = subprocess.Popen(
        ["sh", "-c", script],
        env={**os.environ, "KEYFILE": str(key), "UFW_OPENED": "0"},
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "still here"
    proc.stdout.close()
    proc.wait(timeout=30)
    assert not key.exists()


def _free_setup_port(tmp_path: Path, holders: dict[int, str]) -> subprocess.CompletedProcess[str]:
    """free_setup_port() with `ss` listing ``holders`` (pid → its command
    line) as listening on the port for as long as each process lives."""
    table = tmp_path / "holders.txt"
    table.write_text("".join(f"{pid} {args}\n" for pid, args in holders.items()), encoding="utf-8")
    _stub(
        tmp_path,
        "ss",
        f'while read -r pid args; do kill -0 "$pid" 2>/dev/null && '
        f'echo "LISTEN 0 5 0.0.0.0:8420 0.0.0.0:* users:((\\"x\\",pid=$pid,fd=3))"; '
        f'done < "{table}"\n',
    )
    _stub(
        tmp_path,
        "ps",
        f'pid="$4"\ngrep "^$pid " "{table}" | cut -d" " -f2-\n',
    )
    return _run(
        HELPERS + _function("free_setup_port") + "free_setup_port\necho after\n",
        {"SUDO": "", "PORT": "8420"},
        tmp_path,
    )


def _orphan_sleep() -> int:
    """A process that is not this test's child, like a page an earlier run
    left behind: once stopped it is reaped by init, not left as a zombie."""
    out = subprocess.run(
        ["sh", "-c", "sleep 300 >/dev/null 2>&1 & echo $!"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return int(out.stdout.strip())


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/status").read_text(encoding="utf-8").find("State:\tZ") < 0


def test_a_setup_page_an_earlier_run_left_open_is_closed_for_a_new_one(tmp_path: Path) -> None:
    """#646: a page left behind (its install gone, or an installer before
    this fix) held port 8420, and the rerun failed with a traceback."""
    page = _orphan_sleep()
    try:
        result = _free_setup_port(tmp_path, {page: "python3 /opt/palaia/setup-page.py --port 8420"})
        assert result.returncode == 0, result.stderr
        assert "a setup page from an earlier run is still open" in result.stdout
        assert result.stdout.strip().endswith("after")
        assert not _alive(page)  # it was stopped
    finally:
        if _alive(page):
            os.kill(page, signal.SIGKILL)


def test_another_program_on_the_setup_port_is_named_and_left_alone(tmp_path: Path) -> None:
    other = _orphan_sleep()
    try:
        result = _free_setup_port(tmp_path, {other: "/usr/sbin/some-web-server"})
        assert result.returncode != 0
        assert "port 8420 is used by another program (/usr/sbin/some-web-server)" in result.stderr
        assert "Traceback" not in result.stderr
        assert "after" not in result.stdout
        assert _alive(other)
    finally:
        os.kill(other, signal.SIGKILL)


def test_a_free_setup_port_needs_nothing(tmp_path: Path) -> None:
    result = _free_setup_port(tmp_path, {})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "after"
