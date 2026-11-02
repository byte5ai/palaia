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
        "systemd/palaia-http-redirect.service",
        "http-redirect.sh",
    ):
        path = PI_IMAGE_ROOT / name
        assert path.is_file(), f"missing {path} — SPEC-603 deliverable"


def test_scripts_are_executable_and_parse() -> None:
    for name in ("build.sh", "inspect.sh", "pin-base-image.sh", "http-redirect.sh"):
        path = PI_IMAGE_ROOT / name
        assert path.stat().st_mode & 0o111, f"{path} is not executable"
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"{path} failed to parse:\n{result.stderr}"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not on PATH")
@pytest.mark.parametrize(
    "name", ["build.sh", "inspect.sh", "pin-base-image.sh", "http-redirect.sh"]
)
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
    assert "ghcr.io/byte5ai/palaia:stable" in unit, (
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
# Issue #620: http://palaia.local/ without a port. A oneshot unit on the box
# adds a kernel redirect of incoming port 80 to the container's own port
# (nftables, a table of its own) unless port 80 is already taken. No proxy,
# so nginx still sees each caller's address (SPEC-502's per-client limit).
# ---------------------------------------------------------------------------

SYSTEMD_DIR = PI_IMAGE_ROOT / "systemd"
REDIRECT_UNIT = SYSTEMD_DIR / "palaia-http-redirect.service"
REDIRECT_SCRIPT = PI_IMAGE_ROOT / "http-redirect.sh"
#: Where build.sh installs the script on the image.
INSTALLED_SCRIPT = "/usr/local/lib/palaia/http-redirect"


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
    the Dockerfile so the redirect cannot drift from it."""
    dockerfile = (DEPLOY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"\bPUBLIC_PORT=(\d+)", dockerfile)
    assert match, "v3/deploy/Dockerfile no longer sets PUBLIC_PORT — update this test"
    return match.group(1)


def _fake_tools(tmp_path: Path, *, port_80_taken: bool, nft_fails: bool = False) -> Path:
    """`ss` and `nft` stand-ins on PATH: `ss` reports a listener on port 80
    or none, `nft` records its arguments and stdin and succeeds or fails."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    listener = "LISTEN 0 511 0.0.0.0:80 0.0.0.0:*" if port_80_taken else ""
    (bin_dir / "ss").write_text(
        f'#!/bin/sh\necho "$@" >> "{tmp_path}/ss.args"\n'
        + (f'echo "{listener}"\n' if listener else "")
        + "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "nft").write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{tmp_path}/nft.args"\n'
        f'if [ "$1" = "-f" ]; then cat >> "{tmp_path}/nft.stdin"; fi\n'
        + ("exit 1\n" if nft_fails else "exit 0\n"),
        encoding="utf-8",
    )
    for tool in ("ss", "nft"):
        (bin_dir / tool).chmod(0o755)
    return bin_dir


def _run_script(tmp_path: Path, action: str, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(REDIRECT_SCRIPT), action],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_with_port_80_free_the_redirect_leads_to_the_hubs_own_port(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "start", _fake_tools(tmp_path, port_80_taken=False))
    assert result.returncode == 0, result.stderr
    ruleset = _read(tmp_path / "nft.stdin")
    port = _container_public_port()
    assert f"fib daddr type local tcp dport 80 redirect to :{port}" in ruleset, ruleset
    assert "type nat hook prerouting priority dstnat;" in ruleset
    # `inet`: one rule for IPv4 and IPv6 — an `ip` table would leave IPv6 out.
    assert re.findall(r"\btable (\w+) palaia_http", ruleset) == ["inet"] * 3
    assert result.stdout.strip().splitlines() == [
        f"palaia-http-redirect: port 80 now leads to the hub on :{port}"
    ]


def test_every_start_replaces_the_table_in_one_transaction(tmp_path: Path) -> None:
    """Idempotent: create-if-missing, delete, define — in one `nft -f`, so a
    second start neither fails nor adds a second rule."""
    bin_dir = _fake_tools(tmp_path, port_80_taken=False)
    for _ in range(2):
        assert _run_script(tmp_path, "start", bin_dir).returncode == 0
    ruleset = _read(tmp_path / "nft.stdin")
    once = ruleset[: len(ruleset) // 2]
    assert ruleset == once * 2, "both starts must apply the same full replacement"
    lines = [line.strip() for line in once.splitlines() if line.strip()]
    assert lines[:2] == ["table inet palaia_http", "delete table inet palaia_http"]
    assert _read(tmp_path / "nft.args").splitlines() == ["-f -", "-f -"]


def test_with_port_80_taken_nothing_is_redirected(tmp_path: Path) -> None:
    """An owner's own web server keeps port 80; a redirect left from an
    earlier boot is removed, never added."""
    result = _run_script(tmp_path, "start", _fake_tools(tmp_path, port_80_taken=True))
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "nft.stdin").exists(), "no ruleset may be loaded"
    assert _read(tmp_path / "nft.args").splitlines() == ["delete table inet palaia_http"]
    assert "-Hltn sport = :80" in _read(tmp_path / "ss.args")
    assert len(result.stdout.strip().splitlines()) == 1
    assert "already in use" in result.stdout


def test_a_failing_nft_fails_the_unit_with_one_plain_line(tmp_path: Path) -> None:
    bin_dir = _fake_tools(tmp_path, port_80_taken=False, nft_fails=True)
    result = _run_script(tmp_path, "start", bin_dir)
    assert result.returncode == 1
    assert result.stdout.strip().splitlines() == [
        f"palaia-http-redirect: could not set up port 80 (nft's error is above); "
        f"the hub answers on :{_container_public_port()}"
    ]


def test_stop_removes_the_whole_table_and_never_fails(tmp_path: Path) -> None:
    bin_dir = _fake_tools(tmp_path, port_80_taken=False, nft_fails=True)
    result = _run_script(tmp_path, "stop", bin_dir)
    assert result.returncode == 0
    assert _read(tmp_path / "nft.args").splitlines() == ["delete table inet palaia_http"]


def test_the_redirect_unit_runs_the_installed_script_once_at_boot() -> None:
    assert _values(REDIRECT_UNIT, "Type") == ["oneshot"]
    assert _values(REDIRECT_UNIT, "RemainAfterExit") == ["yes"]
    assert _values(REDIRECT_UNIT, "ExecStart") == [f"{INSTALLED_SCRIPT} start"]
    assert _values(REDIRECT_UNIT, "ExecStop") == [f"{INSTALLED_SCRIPT} stop"]
    assert _values(REDIRECT_UNIT, "WantedBy") == ["multi-user.target"]


def test_the_redirect_runs_after_the_boot_so_a_web_server_on_the_box_wins() -> None:
    """Ordered after multi-user.target, so another service's port-80 listener
    exists by the time the script checks for one."""
    assert "multi-user.target" in " ".join(_values(REDIRECT_UNIT, "After")).split()


def test_the_redirect_unit_may_only_change_the_ruleset() -> None:
    assert _values(REDIRECT_UNIT, "CapabilityBoundingSet") == ["CAP_NET_ADMIN"]
    assert _values(REDIRECT_UNIT, "NoNewPrivileges") == ["yes"]
    assert _values(REDIRECT_UNIT, "ProtectSystem") == ["strict"]


def test_the_hub_and_the_redirect_do_not_depend_on_each_other() -> None:
    """The redirect skipped or failed must never take the hub down, and a
    stopped hub must not stop the redirect."""
    for key in ("Requires", "Requisite", "BindsTo", "PartOf", "Upholds", "Wants"):
        for value in _values(REDIRECT_UNIT, key):
            assert "palaia.service" not in value.split(), f"{key}={value}"
    palaia = (SYSTEMD_DIR / "palaia.service").read_text(encoding="utf-8")
    assert "palaia-http-redirect" not in palaia


def test_build_sh_installs_nftables_the_script_and_the_unit_and_enables_it() -> None:
    build_sh = (PI_IMAGE_ROOT / "build.sh").read_text(encoding="utf-8")
    assert re.search(r"apt-get install -y --no-install-recommends .*\bnftables\b", build_sh), (
        "build.sh no longer installs nftables — the redirect has no `nft`"
    )
    assert (
        'install -D -m 755 "${SCRIPT_DIR}/http-redirect.sh" '
        f'"${{rootfs}}{INSTALLED_SCRIPT}"' in build_sh
    ), "build.sh no longer installs the http-redirect script where the unit runs it"
    assert (
        'install -m 644 "${SCRIPT_DIR}/systemd/palaia-http-redirect.service" '
        '"${rootfs}/etc/systemd/system/palaia-http-redirect.service"' in build_sh
    )
    assert re.search(r"systemctl --root=.* enable .*palaia-http-redirect\.service", build_sh), (
        "build.sh no longer enables palaia-http-redirect.service — port 80 would stay closed"
    )
    assert re.search(r"systemctl --root=.* disable nftables\.service", build_sh), (
        "nftables.service must stay off: its default config flushes the whole ruleset"
    )


def test_inspect_sh_checks_the_redirect_against_what_the_script_says() -> None:
    """Every exact text inspect.sh requires of the installed script must be in
    the script — otherwise a correct image fails inspection, or the check
    drifted from what the image ships."""
    inspect_sh = (PI_IMAGE_ROOT / "inspect.sh").read_text(encoding="utf-8")
    script = REDIRECT_SCRIPT.read_text(encoding="utf-8")
    assert "multi-user.target.wants/palaia-http-redirect.service" in inspect_sh
    assert "nftables.service" in inspect_sh and "/usr/sbin/nft" in inspect_sh
    fixed = re.findall(r"grep -qF '([^']+)' \"\$\{REDIRECT_SCRIPT\}\"", inspect_sh)
    fixed += re.findall(r"grep -qF \"([^\"]+)\" \"\$\{REDIRECT_SCRIPT\}\"", inspect_sh)
    exact = re.findall(r"grep -qx '([^']+)' \"\$\{REDIRECT_SCRIPT\}\"", inspect_sh)
    assert fixed and exact, "inspect.sh no longer checks the script's rule and port"
    for text in fixed:
        assert text in script, f"inspect.sh requires {text!r} of the script"
    script_lines = [line.strip() for line in script.splitlines()]
    for line in exact:
        assert line in script_lines, f"inspect.sh requires the line {line!r} of the script"
    assert f"HUB_PORT={_container_public_port()}" in exact


def test_the_pi_keeps_the_cloud_entry_on_loopback() -> None:
    """On the host network the container's cloud entry (8422) would listen on
    every address of the Pi; a tunnel reaches it on loopback."""
    unit = (SYSTEMD_DIR / "palaia.service").read_text(encoding="utf-8")
    assert "-e PALAIA_CLOUD_BIND=127.0.0.1" in unit
    inspect_sh = (PI_IMAGE_ROOT / "inspect.sh").read_text(encoding="utf-8")
    assert "-e PALAIA_CLOUD_BIND=127.0.0.1" in inspect_sh


_SYSTEMD_ANALYZE = shutil.which("systemd-analyze")


def _unit_for_verify(tmp_path: Path) -> Path:
    """The unit with ExecStart/ExecStop pointing at the repo's script, so
    `systemd-analyze verify` finds an executable on a build host too."""
    script = tmp_path / "http-redirect"
    shutil.copy(REDIRECT_SCRIPT, script)
    script.chmod(0o755)
    unit = tmp_path / REDIRECT_UNIT.name
    unit.write_text(
        REDIRECT_UNIT.read_text(encoding="utf-8").replace(INSTALLED_SCRIPT, str(script)),
        encoding="utf-8",
    )
    return unit


@pytest.mark.skipif(_SYSTEMD_ANALYZE is None, reason="needs systemd-analyze (a systemd host)")
def test_the_redirect_unit_passes_systemd_analyze_verify(tmp_path: Path) -> None:
    assert _SYSTEMD_ANALYZE is not None
    unit = _unit_for_verify(tmp_path)
    result = subprocess.run(
        [_SYSTEMD_ANALYZE, "verify", str(unit)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # verify exits 0 on a value it cannot parse and only warns, naming the
    # unit — so any line about this unit counts as a failure.
    complaints = [
        line for line in (result.stdout + result.stderr).splitlines() if unit.name in line
    ]
    assert result.returncode == 0 and not complaints, result.stdout + result.stderr


def test_readme_states_a_size_budget_matching_build_sh() -> None:
    readme = (PI_IMAGE_ROOT / "README.md").read_text(encoding="utf-8")
    build_sh = (PI_IMAGE_ROOT / "build.sh").read_text(encoding="utf-8")

    budget_match = re.search(r"SIZE_BUDGET_MB:-(\d+)", build_sh)
    assert budget_match, "build.sh has no PI_IMAGE_SIZE_BUDGET_MB default to check against"
    budget = budget_match.group(1)
    assert budget in readme, (
        f"README.md's stated size budget doesn't mention build.sh's actual default ({budget}MB)"
    )
