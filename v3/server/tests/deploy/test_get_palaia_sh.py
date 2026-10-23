"""Pieces of ``v3/deploy/get-palaia.sh`` run for real in ``sh``.

The installer as a whole needs root, Docker and Tailscale and is exercised on
a real server; these tests take single functions out of the shipped file and
run them against stand-ins, so the logic itself is checked, not its text.
"""

from __future__ import annotations

import os
import re
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
