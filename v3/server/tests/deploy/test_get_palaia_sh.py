"""Pieces of ``v3/deploy/get-palaia.sh`` run for real in ``sh``.

The installer as a whole needs root, Docker and Tailscale and is exercised on
a real server; these tests take single functions out of the shipped file and
run them against stand-ins, so the logic itself is checked, not its text.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
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
