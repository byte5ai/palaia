"""The runtime image installs every binary the hub runs as a subprocess.

The vault engine drives each vault's git repository through the `git` binary
(``palaia_hub/vault/gitlayer.py``). The image once shipped without it, so the
container started and answered /api/health, but creating a vault failed. The
docker smoke test (``server/tests/e2e/test_docker_one_liner_smoke.py``)
creates a vault in the real container where a daemon exists; this text check
catches the same regression on a machine without one.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[3] / "deploy" / "Dockerfile"


def _runtime_stage() -> str:
    text = DOCKERFILE.read_text(encoding="utf-8")
    start = text.index("AS runtime")
    return text[start:]


def _apt_packages(stage: str) -> set[str]:
    packages: set[str] = set()
    for match in re.finditer(r"apt-get install\s+([^&]+)", stage):
        words = match.group(1).replace("\\", " ").split()
        packages.update(word for word in words if not word.startswith("-"))
    return packages


def test_the_runtime_stage_installs_git() -> None:
    assert "git" in _apt_packages(_runtime_stage()), (
        "the runtime image does not install git; every vault operation needs it"
    )
