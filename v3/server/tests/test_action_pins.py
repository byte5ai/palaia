"""Issue #400: third-party GitHub Actions in the v3 workflows are pinned by
commit SHA, and a bot is configured to keep those pins current.

Both halves have to hold together. A SHA pin without a bot rots into a
frozen, unpatched action; a bot without SHA pins leaves the release workflow
— which holds ``packages: write`` and a GHCR login — trusting a mutable
major tag. Re-tagging ``@v4`` is the cheap move in a compromised-action
supply-chain attack, and it is exactly what a SHA pin removes, so this is
checked rather than left to review.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"

# owner/repo[/subdir…]@<40 hex>. Anything shorter is an abbreviated SHA or a
# tag, both of which GitHub resolves mutably.
_SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _v3_workflows() -> list[Path]:
    paths = sorted(_WORKFLOW_DIR.glob("v3-*.yml"))
    assert paths, "no v3 workflows found — did they move?"
    return paths


def _uses_values(workflow: dict) -> list[str]:
    values: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            uses = step.get("uses")
            if uses:
                values.append(uses)
    return values


@pytest.mark.parametrize("path", _v3_workflows(), ids=lambda p: p.name)
def test_every_third_party_action_is_pinned_by_commit_sha(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    for uses in _uses_values(workflow):
        # Local composite actions and reusable workflows in this repository
        # are versioned by the commit that runs them; only third-party
        # references need pinning.
        if uses.startswith("./"):
            continue
        assert _SHA_PIN.match(uses), (
            f"{path.name}: `uses: {uses}` is not pinned to a full commit SHA "
            "(issue #400). Resolve the tag to its commit and keep the version "
            "as a trailing `# vX.Y.Z` comment."
        )


def test_dependabot_keeps_the_pins_current() -> None:
    assert _DEPENDABOT.exists(), (
        "issue #400: the SHA pins in .github/workflows/v3-*.yml are only an "
        "improvement while something bumps them — .github/dependabot.yml is "
        "that something and must not be removed."
    )
    config = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}
    assert "github-actions" in ecosystems
    # The v3 hub image's base images are digest-pinned (see the note in
    # v3/deploy/Dockerfile) and watched here, so Dependabot keeps each digest
    # current instead of letting it rot into a frozen, unpatched base.
    assert "docker" in ecosystems


_DOCKERFILE = _REPO_ROOT / "v3" / "deploy" / "Dockerfile"
# A registry image reference in `FROM`/`COPY --from=` — as opposed to a
# build-stage alias like `hub-build`, which carries no tag, registry or digest.
_STAGE_ALIAS = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_IMAGE_REF = re.compile(r"^(?:FROM\s+(\S+)|COPY\s+--from=(\S+))", re.MULTILINE)


def test_dockerfile_base_images_are_pinned_by_digest() -> None:
    assert _DOCKERFILE.exists(), "issue #400: v3/deploy/Dockerfile moved?"
    text = _DOCKERFILE.read_text(encoding="utf-8")
    refs = [m.group(1) or m.group(2) for m in _IMAGE_REF.finditer(text)]
    assert refs, "no FROM/COPY --from references found — did the Dockerfile move?"
    images = [r for r in refs if not _STAGE_ALIAS.match(r)]
    assert images, "expected at least one registry image reference"
    for image in images:
        assert "@sha256:" in image, (
            f"v3/deploy/Dockerfile: base image `{image}` is not pinned by digest "
            "(issue #400). Resolve the tag against the registry and pin it as "
            "`image:tag@sha256:<hex>`; keep the tag for readability."
        )
