"""``v3/deploy/install.sh`` (``get.palaia.ai/docker``): which network it picks.

On Linux the container runs on the host network so ``palaia.local`` reaches
the other devices (issue #619), with the cloud entry kept on loopback; on
Docker Desktop, whose containers live in a virtual machine, it publishes the
port instead. Runs the real script against a stand-in ``docker`` that
records what it was asked to do.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[3] / "deploy" / "install.sh"


def _run(tmp_path: Path, operating_system: str, **env: str) -> tuple[list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "run-args"
    fake = bin_dir / "docker"
    fake.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            case "$1" in
              info) [ "$2" = "--format" ] && echo "{operating_system}"; exit 0 ;;
              pull) exit 0 ;;
              inspect) exit 1 ;;
              run) shift; for arg in "$@"; do echo "$arg"; done > "{record}"; exit 0 ;;
            esac
            exit 1
            """
        ),
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(INSTALL_SH)],  # noqa: S607
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return record.read_text(encoding="utf-8").splitlines(), result.stdout


def test_linux_runs_on_the_host_network_with_the_cloud_entry_on_loopback(tmp_path: Path) -> None:
    args, out = _run(tmp_path, "Ubuntu 24.04.3 LTS")
    assert args[args.index("--network") + 1] == "host"
    assert "PALAIA_CLOUD_BIND=127.0.0.1" in args
    assert "-p" not in args
    assert "http://palaia.local:8420/" in out


@pytest.mark.parametrize("name", ["Docker Desktop", "docker desktop for linux"])
def test_docker_desktop_publishes_the_port_instead(tmp_path: Path, name: str) -> None:
    args, out = _run(tmp_path, name)
    assert args[args.index("-p") + 1] == "8420:8420"
    assert "--network" not in args
    assert not any(arg.startswith("PALAIA_CLOUD_BIND") for arg in args)
    assert "http://localhost:8420/" in out
    assert "http://palaia.local" not in out


def test_another_port_on_the_host_network_moves_the_hub_itself(tmp_path: Path) -> None:
    args, out = _run(tmp_path, "Debian GNU/Linux 13", PALAIA_INSTALL_PORT="9420")
    assert "PUBLIC_PORT=9420" in args
    assert "http://palaia.local:9420/" in out


def test_both_networks_keep_the_hardening_flags(tmp_path: Path) -> None:
    for name, sub in (("Ubuntu 24.04.3 LTS", "linux"), ("Docker Desktop", "desktop")):
        workdir = tmp_path / sub
        workdir.mkdir()
        args, _ = _run(workdir, name)
        joined = " ".join(args)
        for flag in (
            "--restart unless-stopped",
            "--security-opt no-new-privileges:true",
            "--cap-drop ALL",
            "--read-only",
            "--tmpfs /tmp",
            "--tmpfs /run",
        ):
            assert flag in joined, (name, flag)
