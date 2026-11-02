"""SPEC-603: static, no-privilege checks on the Pi appliance image pipeline
(``v3/deploy/pi-image/``).

This file cannot itself loop-mount, chroot into, or boot anything — that
needs root, real loop devices, and (for the boot half) real hardware, none
of which this test environment has. What it *can* and does check, matching
this repo's own established pattern for deploy artifacts CI can't fully
exercise (``test_cloud_init.py``'s docstring makes the same point for
SPEC-601):

1. The pieces the real pipeline is built from are internally consistent —
   ``base-image.env``'s pinned URL and checksum look like a real, matched
   pair; ``systemd/palaia.service`` never forks ``install.sh``'s own
   SPEC-502 hardening flag list (the same drift-test pattern
   ``test_cloud_init.py`` already applies); the shell scripts at least
   parse (``bash -n``).
2. The things ``.github/workflows/v3-pi-image.yml`` and ``inspect.sh``
   assert at runtime (Docker enabled, palaia unit enabled, mDNS on, SSH
   off) are assertions this file can *also* make about the static unit
   file, one layer removed from a real rootfs — so a change that would
   obviously break one of those four assertions is caught here too,
   without waiting for the next real image build.

The actual "does it build, is it reproducible, does it pass inspection"
proof is the real ``workflow_dispatch``/release-tag run of
``v3-pi-image.yml`` — see that run's link in this SPEC's PR description,
not this file.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# v3/server/tests/deploy -> v3/server/tests -> v3/server -> v3 -> v3/deploy
DEPLOY_ROOT = Path(__file__).resolve().parents[3] / "deploy"
PI_IMAGE_ROOT = DEPLOY_ROOT / "pi-image"

#: Same extractor pattern test_cloud_init.py uses — pulled from install.sh's
#: own text so this test cannot drift from the real flag list on either
#: side.
_HARDENING_BLOCK_RE = re.compile(r"--restart unless-stopped.*?--tmpfs /run", re.DOTALL)


def _extract_hardening_flags(install_sh_text: str) -> list[str]:
    match = _HARDENING_BLOCK_RE.search(install_sh_text)
    assert match, (
        "install.sh's docker run block no longer has the expected shape "
        "(looked for '--restart unless-stopped' ... '--tmpfs /run') — "
        "update this extractor to match, never hand-copy the flag list instead"
    )
    lines = [line.strip().rstrip("\\").strip() for line in match.group(0).splitlines()]
    # install.sh's own block starts with a flag this appliance's systemd
    # unit deliberately does not repeat (`--restart unless-stopped`
    # duplicates systemd's own `Restart=`/`RestartSec=`, which
    # palaia.service already sets) — every *other* line is the SPEC-502
    # hardening set proper, which must match verbatim.
    return [line for line in lines if line and line != "--restart unless-stopped"]


def test_pi_image_directory_layout() -> None:
    for name in (
        "README.md",
        "BOOT-TEST.md",
        "base-image.env",
        "build.sh",
        "inspect.sh",
        "pin-base-image.sh",
        "systemd/palaia.service",
        "systemd/palaia-http.socket",
        "systemd/palaia-http.service",
    ):
        path = PI_IMAGE_ROOT / name
        assert path.is_file(), f"missing {path} — SPEC-603 deliverable"


def test_scripts_are_executable_and_parse() -> None:
    for name in ("build.sh", "inspect.sh", "pin-base-image.sh"):
        path = PI_IMAGE_ROOT / name
        assert path.stat().st_mode & 0o111, f"{path} is not executable"
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"{path} failed to parse:\n{result.stderr}"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not on PATH")
@pytest.mark.parametrize("name", ["build.sh", "inspect.sh", "pin-base-image.sh"])
def test_scripts_pass_shellcheck(name: str) -> None:
    result = subprocess.run(
        ["shellcheck", "--severity=warning", str(PI_IMAGE_ROOT / name)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_base_image_env_is_a_matched_pinned_pair() -> None:
    text = (PI_IMAGE_ROOT / "base-image.env").read_text(encoding="utf-8")

    url_match = re.search(r'BASE_IMAGE_URL="([^"]+)"', text)
    sha_match = re.search(r'BASE_IMAGE_SHA256="([0-9a-f]{64})"', text)
    assert url_match, "base-image.env has no BASE_IMAGE_URL"
    assert sha_match, "base-image.env has no 64-hex-char BASE_IMAGE_SHA256"

    url = url_match.group(1)
    assert url.startswith("https://downloads.raspberrypi.org/raspios_lite_arm64/"), (
        f"BASE_IMAGE_URL does not look like a Raspberry Pi OS Lite (arm64) release: {url!r}"
    )
    assert url.endswith(".img.xz"), f"BASE_IMAGE_URL should point at a .img.xz: {url!r}"
    assert "lite" in url.lower(), f"BASE_IMAGE_URL should be the Lite build, not desktop: {url!r}"
    assert "arm64" in url.lower(), f"BASE_IMAGE_URL should be arm64, not armhf: {url!r}"


def test_palaia_service_hardening_flags_match_install_sh_verbatim() -> None:
    """Drift test: the Pi appliance's systemd unit must reuse install.sh's
    own SPEC-502 hardening flags verbatim, never a second, forked copy —
    same pattern test_cloud_init.py already applies to cloud-init.yaml."""
    install_sh = (DEPLOY_ROOT / "install.sh").read_text(encoding="utf-8")
    unit = (PI_IMAGE_ROOT / "systemd" / "palaia.service").read_text(encoding="utf-8")

    flags = _extract_hardening_flags(install_sh)
    assert flags, "no hardening flags extracted from install.sh"
    for flag in flags:
        assert flag in unit, (
            f"palaia.service's docker run command is missing install.sh's own "
            f"{flag!r} flag — the two must never fork this list"
        )


def test_palaia_service_runs_the_stable_channel_image() -> None:
    unit = (PI_IMAGE_ROOT / "systemd" / "palaia.service").read_text(encoding="utf-8")
    assert "ghcr.io/byte5ai/palaia-hub:stable" in unit, (
        "the appliance must run the :stable release channel (SPEC-501), not a moving tag"
    )


def test_palaia_service_is_installed_and_enabled_by_wanted_by() -> None:
    unit = (PI_IMAGE_ROOT / "systemd" / "palaia.service").read_text(encoding="utf-8")
    assert "[Install]" in unit and "WantedBy=multi-user.target" in unit, (
        "palaia.service has no [Install] WantedBy=multi-user.target — "
        "`systemctl --root=<rootfs> enable palaia.service` (build.sh) has nothing to act on"
    )


def test_palaia_service_uses_host_networking_for_mdns() -> None:
    """'mDNS on' (SPEC-603 acceptance) depends on the container reaching the
    host's real network — see mdns_announce.py's own docstring for why
    Docker's default bridge network can't do this."""
    unit = (PI_IMAGE_ROOT / "systemd" / "palaia.service").read_text(encoding="utf-8")
    assert "--network host" in unit
    assert "PALAIA_MDNS_ENABLED=0" not in unit


def test_build_sh_enables_docker_and_disables_ssh() -> None:
    build_sh = (PI_IMAGE_ROOT / "build.sh").read_text(encoding="utf-8")
    assert re.search(r"systemctl --root=.* enable .*docker\.service", build_sh), (
        "build.sh no longer enables docker.service — "
        "'Docker enabled' assertion would have nothing behind it"
    )
    assert re.search(r"systemctl --root=.* enable .*palaia\.service", build_sh), (
        "build.sh no longer enables palaia.service"
    )
    assert "disable ssh.service" in build_sh, (
        "build.sh should explicitly (and idempotently) disable ssh.service, "
        "not rely only on the base image's own default — see README.md"
    )
    assert "apt-get install" in build_sh and "docker.io" in build_sh


def test_inspect_sh_asserts_the_four_spec_603_properties() -> None:
    """The SPEC's own acceptance wording: 'loop-mount inspection asserts:
    Docker enabled, palaia unit enabled, mDNS on, SSH off'."""
    inspect_sh = (PI_IMAGE_ROOT / "inspect.sh").read_text(encoding="utf-8")
    for marker in (
        "docker.service",
        "palaia.service",
        "--network host",
        "ssh.service",
    ):
        assert marker in inspect_sh, f"inspect.sh no longer checks for {marker!r}"


def test_workflow_is_dispatch_and_tag_only_never_pr() -> None:
    workflow_path = (
        Path(__file__).resolve().parents[4] / ".github" / "workflows" / "v3-pi-image.yml"
    )
    assert workflow_path.is_file(), f"missing {workflow_path}"
    text = workflow_path.read_text(encoding="utf-8")

    assert "workflow_dispatch" in text
    assert re.search(r"tags:\s*\[.?v3\.\*.?\]", text), (
        "workflow should trigger on v3.* release tags, matching v3-release.yml's own tags"
    )
    assert "pull_request" not in text, (
        "SPEC-603: 'it must not run on every PR' — "
        "this workflow must never gain a pull_request trigger"
    )


def test_the_release_cut_dispatches_the_pi_image_build_on_the_new_tag() -> None:
    """Issue #341: a tag created with the Actions token does not fire this
    workflow's `push: tags:` trigger, so v3-cut-release.yml must dispatch it
    explicitly — otherwise a release ships with no appliance image."""
    workflows = Path(__file__).resolve().parents[4] / ".github" / "workflows"
    cut = (workflows / "v3-cut-release.yml").read_text(encoding="utf-8")
    assert "gh workflow run v3-pi-image.yml --ref" in cut, (
        "v3-cut-release.yml no longer dispatches the Pi appliance image build"
    )
    # Ordered after the release exists, so the image attaches to it.
    assert cut.index("gh release create") < cut.index("gh workflow run v3-pi-image.yml")
    assert "actions: write" in cut

    pi = (workflows / "v3-pi-image.yml").read_text(encoding="utf-8")
    assert "release creation is an owner step" not in pi, (
        "stale: the release is created by v3-cut-release.yml since #305"
    )
    releasing = (Path(__file__).resolve().parents[3] / "RELEASING.md").read_text(encoding="utf-8")
    assert "v3-pi-image.yml" in releasing


# ---------------------------------------------------------------------------
# Issue #620: http://palaia.local/ without a port. A socket on the box binds
# port 80 and systemd-socket-proxyd forwards to the container's own port,
# outside the container, which keeps its SPEC-502 hardening.
# ---------------------------------------------------------------------------

SYSTEMD_DIR = PI_IMAGE_ROOT / "systemd"
HTTP_SOCKET = SYSTEMD_DIR / "palaia-http.socket"
HTTP_SERVICE = SYSTEMD_DIR / "palaia-http.service"
#: Where Raspberry Pi OS (Debian trixie, merged /usr) ships the proxy, in
#: the `systemd` package itself — see inspect.sh's matching check.
PROXYD = "/usr/lib/systemd/systemd-socket-proxyd"


def _unit_lines(path: Path) -> list[str]:
    """The unit's directive lines, comments and blanks dropped."""
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith(("#", ";")):
            lines.append(line)
    return lines


def _values(path: Path, key: str) -> list[str]:
    prefix = f"{key}="
    return [line[len(prefix) :] for line in _unit_lines(path) if line.startswith(prefix)]


def _container_public_port() -> str:
    """The port nginx listens on inside the image (`PUBLIC_PORT`), read from
    the Dockerfile so the forwarder cannot drift from it."""
    dockerfile = (DEPLOY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"\bPUBLIC_PORT=(\d+)", dockerfile)
    assert match, "v3/deploy/Dockerfile no longer sets PUBLIC_PORT — update this test"
    return match.group(1)


def test_the_port_80_socket_listens_on_80_only() -> None:
    assert _values(HTTP_SOCKET, "ListenStream") == ["80"]


def test_a_web_server_on_the_box_keeps_port_80() -> None:
    """An owner's own web server (nginx, lighttpd, Pi-hole) must win port 80;
    the forwarder then fails on its own and the hub stays on its port. That
    needs the socket ordered after multi-user.target, which is only legal
    with DefaultDependencies=no (otherwise sockets.target → basic.target →
    multi-user.target and this ordering form a cycle)."""
    assert _values(HTTP_SOCKET, "DefaultDependencies") == ["no"]
    after = " ".join(_values(HTTP_SOCKET, "After")).split()
    assert "multi-user.target" in after
    assert _values(HTTP_SOCKET, "WantedBy") == ["multi-user.target"]
    # DefaultDependencies=no drops these too; a socket still needs them.
    assert "sysinit.target" in " ".join(_values(HTTP_SOCKET, "Requires")).split()
    assert "shutdown.target" in " ".join(_values(HTTP_SOCKET, "Conflicts")).split()


def test_the_forwarder_targets_the_containers_own_port_on_loopback() -> None:
    port = _container_public_port()
    assert _values(HTTP_SERVICE, "ExecStart") == [f"{PROXYD} 127.0.0.1:{port}"], (
        "palaia-http.service must forward to the hub's own port on this box's "
        f"loopback (127.0.0.1:{port}; palaia.service runs the container on the host network)"
    )
    assert _values(HTTP_SERVICE, "Type") == ["notify"]
    requires = " ".join(_values(HTTP_SERVICE, "Requires")).split()
    assert "palaia-http.socket" in requires


def test_the_forwarder_holds_no_privilege() -> None:
    assert _values(HTTP_SERVICE, "DynamicUser") == ["yes"]
    assert _values(HTTP_SERVICE, "NoNewPrivileges") == ["yes"]
    assert _values(HTTP_SERVICE, "CapabilityBoundingSet") == [""], (
        "the proxy only accepts and connects out; systemd binds port 80 for it"
    )
    assert not [v for v in _values(HTTP_SERVICE, "AmbientCapabilities") if v]
    assert not _values(HTTP_SERVICE, "User"), "DynamicUser, never a fixed (root) user"
    assert not _values(HTTP_SERVICE, "PrivateNetwork"), "the proxy must reach 127.0.0.1"


def test_the_hub_and_the_forwarder_do_not_depend_on_each_other() -> None:
    """Port 80 taken, or the forwarder broken, must never take the hub down —
    and a stopped hub must not stop the socket."""
    for unit in (HTTP_SOCKET, HTTP_SERVICE):
        for key in ("Requires", "Requisite", "BindsTo", "PartOf", "Upholds"):
            for value in _values(unit, key):
                assert "palaia.service" not in value.split(), f"{unit.name}: {key}={value}"
    palaia = (SYSTEMD_DIR / "palaia.service").read_text(encoding="utf-8")
    assert "palaia-http" not in palaia


def test_build_sh_installs_both_forwarder_units_and_enables_the_socket() -> None:
    build_sh = (PI_IMAGE_ROOT / "build.sh").read_text(encoding="utf-8")
    for name in ("palaia-http.socket", "palaia-http.service"):
        assert re.search(
            rf'install -m 644 "\$\{{SCRIPT_DIR\}}/systemd/{re.escape(name)}" '
            rf'"\$\{{rootfs\}}/etc/systemd/system/{re.escape(name)}"',
            build_sh,
        ), f"build.sh no longer installs {name}"
    assert re.search(r"systemctl --root=.* enable .*palaia-http\.socket", build_sh), (
        "build.sh no longer enables palaia-http.socket — nothing would answer on port 80"
    )


def test_inspect_sh_checks_the_forwarder_against_the_real_unit_lines() -> None:
    """Every exact line inspect.sh requires of the forwarder units must be a
    line of those units — otherwise a correct image fails inspection, or the
    check drifted from what the image ships."""
    inspect_sh = (PI_IMAGE_ROOT / "inspect.sh").read_text(encoding="utf-8")
    assert "multi-user.target.wants/palaia-http.socket" in inspect_sh
    assert PROXYD in inspect_sh
    required = dict(
        re.findall(r"grep -qx '([^']+)' \"\$\{(HTTP_SOCKET|HTTP_SERVICE)\}\"", inspect_sh)
    )
    by_unit = {"HTTP_SOCKET": HTTP_SOCKET, "HTTP_SERVICE": HTTP_SERVICE}
    found = {var: line for line, var in required.items()}
    assert set(found) == {"HTTP_SOCKET", "HTTP_SERVICE"}, (
        "inspect.sh should check one exact line of each forwarder unit "
        "(the socket's port, the service's target)"
    )
    for var, line in found.items():
        assert line in _unit_lines(by_unit[var]), f"inspect.sh requires {line!r} of {var}"


_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")


@pytest.mark.skipif(
    _SYSTEMD_ANALYZE is None or not Path(PROXYD).exists(),
    reason="needs systemd-analyze and systemd-socket-proxyd (a systemd Linux host)",
)
def test_the_forwarder_units_pass_systemd_analyze_verify() -> None:
    assert _SYSTEMD_ANALYZE is not None
    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", str(HTTP_SOCKET), str(HTTP_SERVICE)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(
    _SYSTEMD_ANALYZE is None or not Path(PROXYD).exists(),
    reason="needs systemd-analyze and systemd-socket-proxyd (a systemd Linux host)",
)
def test_enabling_the_socket_creates_no_ordering_cycle_at_boot(tmp_path: Path) -> None:
    """Pull the socket into the host's multi-user.target the way
    `systemctl enable` does and let systemd build the boot transaction.
    With default dependencies this exact unit produces 'Found ordering
    cycle … dependency on palaia-http.socket'."""
    assert _SYSTEMD_ANALYZE is not None
    wants = tmp_path / "multi-user.target.wants"
    wants.mkdir()
    for unit in (HTTP_SOCKET, HTTP_SERVICE):
        shutil.copy(unit, tmp_path / unit.name)
    (wants / HTTP_SOCKET.name).symlink_to(tmp_path / HTTP_SOCKET.name)
    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", "multi-user.target"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "SYSTEMD_UNIT_PATH": f"{tmp_path}:"},
    )
    output = result.stdout + result.stderr
    cycle_lines = [
        line for line in output.splitlines() if "palaia-http" in line and "cycle" in line.lower()
    ] + [line for line in output.splitlines() if "dependency on palaia-http" in line]
    assert not cycle_lines, "\n".join(cycle_lines)


def test_readme_states_a_size_budget_matching_build_sh() -> None:
    readme = (PI_IMAGE_ROOT / "README.md").read_text(encoding="utf-8")
    build_sh = (PI_IMAGE_ROOT / "build.sh").read_text(encoding="utf-8")

    budget_match = re.search(r"SIZE_BUDGET_MB:-(\d+)", build_sh)
    assert budget_match, "build.sh has no PI_IMAGE_SIZE_BUDGET_MB default to check against"
    budget = budget_match.group(1)
    assert budget in readme, (
        f"README.md's stated size budget doesn't mention build.sh's actual default ({budget}MB)"
    )
