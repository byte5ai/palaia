"""SPEC-601: the cloud-init VPS install template.

Three things this file proves, matching the SPEC's own acceptance
criteria:

1. ``v3/deploy/cloud-init.yaml`` parses as a valid cloud-config document
   (``cloud-init schema --config-file``, run in CI — see
   :func:`test_cloud_init_schema_validates`'s own docstring for why that
   needs ``uvx`` rather than a plain ``pip install``).
2. Its ``docker run`` command never forks ``install.sh``'s hardening flag
   list — the same "extract, don't hand-copy" drift-test pattern
   ``v3/site/docs/tests/onboarding.test.ts`` already applies to the
   onboarding page's snippets, and
   ``server/tests/e2e/test_docker_one_liner_smoke.py`` already applies to
   its own smoke-test invocation.
3. The one placeholder the SPEC promises ("the Tailscale auth key is the
   ONE placeholder... no other editing required") really is the only one,
   and the hub port is bound so it is reachable over the tailnet only,
   never the public internet.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# v3/server/tests/deploy -> v3/server/tests -> v3/server -> v3 -> v3/deploy
DEPLOY_ROOT = Path(__file__).resolve().parents[3] / "deploy"
CLOUD_INIT_PATH = DEPLOY_ROOT / "cloud-init.yaml"

# The exact pinned tag `test_cloud_init_schema_validates` installs cloud-init
# from. 24.1.3 is the last tagged release still shipping a setuptools
# `pyproject.toml`/`build-backend` — cloud-init's own `main` branch moved to
# a meson build with an intentionally empty `build-backend` ("to avoid RTD
# builds"), which `pip`/`uv` cannot build a wheel from at all. 24.1.3 is
# also the version Ubuntu 24.04 ("noble")'s own `cloud-init` apt package is
# built from, so pinning it here validates against the same real tool a
# fresh Ubuntu VPS actually runs, not an arbitrary snapshot.
CLOUD_INIT_PYPI_REF = "cloud-init @ git+https://github.com/canonical/cloud-init@24.1.3"

#: The block of `docker run` flags in install.sh between the volume mount
#: and the image argument — everything that is *not* specific to a single
#: container instance (`--name`/`-p`/`-v`), i.e. the SPEC-502 hardening set.
#: Extracted from install.sh's own text rather than retyped here, so this
#: test cannot silently drift from the real flag list on either side.
_HARDENING_BLOCK_RE = re.compile(r"--restart unless-stopped.*?--tmpfs /run", re.DOTALL)


def _extract_hardening_flags(install_sh_text: str) -> list[str]:
    match = _HARDENING_BLOCK_RE.search(install_sh_text)
    assert match, (
        "install.sh's docker run block no longer has the expected shape "
        "(looked for '--restart unless-stopped' ... '--tmpfs /run') — "
        "update this extractor to match, never hand-copy the flag list instead"
    )
    lines = [line.strip().rstrip("\\").strip() for line in match.group(0).splitlines()]
    return [line for line in lines if line]


def test_cloud_init_yaml_exists() -> None:
    assert CLOUD_INIT_PATH.is_file(), f"no cloud-init template at {CLOUD_INIT_PATH}"
    assert CLOUD_INIT_PATH.read_text(encoding="utf-8").startswith("#cloud-config"), (
        "cloud-init.yaml must open with the '#cloud-config' header or cloud-init ignores it"
    )


def test_hardening_flags_match_install_sh_verbatim() -> None:
    """Drift test: cloud-init.yaml's docker run must reuse install.sh's own
    hardening flags verbatim, never a second, separately-maintained copy."""
    install_sh = (DEPLOY_ROOT / "install.sh").read_text(encoding="utf-8")
    cloud_init = CLOUD_INIT_PATH.read_text(encoding="utf-8")

    flags = _extract_hardening_flags(install_sh)
    assert flags, "no hardening flags extracted from install.sh"
    for flag in flags:
        assert flag in cloud_init, (
            f"cloud-init.yaml's docker run command is missing install.sh's own {flag!r} "
            "flag — the two must never fork this list"
        )


def test_tailscale_auth_key_is_the_only_placeholder() -> None:
    cloud_init = CLOUD_INIT_PATH.read_text(encoding="utf-8")

    assert "tskey-REPLACE_ME" in cloud_init, (
        "the Tailscale auth key placeholder must be clearly marked as 'tskey-REPLACE_ME'"
    )
    # Every occurrence of the word "REPLACE_ME" is part of that one marker
    # (the header comment names it, the script itself sets it and checks
    # for it) — none stand alone as a second, different placeholder.
    stray = [
        m.start()
        for m in re.finditer("REPLACE_ME", cloud_init)
        if not cloud_init[: m.start()].endswith("tskey-")
    ]
    assert not stray, f"a 'REPLACE_ME' not part of 'tskey-REPLACE_ME' at offset(s) {stray}"
    assert not re.search(r"CHANGE_?ME|YOUR_[A-Z_]+", cloud_init), (
        "found a second placeholder-looking marker besides the Tailscale auth key"
    )


def test_hub_port_is_bound_to_the_tailnet_address_only() -> None:
    """SPEC-601: 'firewalls the hub port so it is reachable via the tailnet
    only' — checked two ways, matching the file's own two layers."""
    cloud_init = CLOUD_INIT_PATH.read_text(encoding="utf-8")

    # Layer 1: the docker publish itself binds to the tailnet address, not
    # every interface (`-p 8420:8420` / `-p 0.0.0.0:8420:8420` would expose
    # it publicly).
    assert '-p "${TAILSCALE_IP}:${PORT}:8420"' in cloud_init
    assert "-p 0.0.0.0" not in cloud_init
    assert '-p "${PORT}:8420"' not in cloud_init

    # Layer 2: a firewall rule scoped to the tailscale interface.
    assert "tailscale0" in cloud_init
    assert "ufw allow in on tailscale0" in cloud_init


def test_cloud_init_schema_validates() -> None:
    """SPEC-601 acceptance: 'cloud-init file passes `cloud-init schema
    --config-file` validation in CI'.

    cloud-init is not on PyPI under a name pip can install directly off its
    current `main` branch (see ``CLOUD_INIT_PYPI_REF``'s comment above for
    why 24.1.3 is pinned instead). ``uvx --from <git ref>`` installs it into
    a throwaway tool environment for exactly this one subprocess call — no
    dependency added to this project's own `pyproject.toml`/lockfile, which
    is the SPEC's own "cheapest clean way" instruction.
    """
    if shutil.which("uvx") is None:
        pytest.skip("uvx not on PATH in this environment")

    result = subprocess.run(
        [
            "uvx",
            "--from",
            CLOUD_INIT_PYPI_REF,
            "cloud-init",
            "schema",
            "--config-file",
            str(CLOUD_INIT_PATH),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Valid schema" in result.stdout, result.stdout + result.stderr
