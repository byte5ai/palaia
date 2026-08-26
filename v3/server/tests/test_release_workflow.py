"""SPEC-501 deliverable #3: "SPEC-112's CI grows a channel input" — the
release workflow bakes PALAIA_CHANNEL and the
``org.opencontainers.image.version`` annotation into the pushed image, and
accepts a manual channel override. This is not something a container build
can be run against in this environment (no docker daemon), so it is
checked structurally instead: the workflow YAML actually wires what
``palaia_hub.update.check_for_update`` reads back.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "workflows" / "v3-release.yml"
)


def _load_workflow() -> dict:
    text = _WORKFLOW_PATH.read_text(encoding="utf-8")
    # PyYAML parses the bare `on:` key as the boolean True (YAML 1.1) —
    # harmless here since this test only reads the "true" key back with
    # the same quirk, but spelled out so a future reader isn't confused by
    # `workflow["true"]` below.
    return yaml.safe_load(text)


def test_workflow_accepts_a_manual_channel_input() -> None:
    workflow = _load_workflow()
    dispatch = workflow[True]["workflow_dispatch"]
    assert "channel" in dispatch["inputs"]
    options = dispatch["inputs"]["channel"]["options"]
    assert set(options) >= {"stable", "beta"}


def test_the_build_step_bakes_palaia_channel_and_a_version_annotation() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    build_step = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action"))

    assert "PALAIA_CHANNEL=" in build_step["with"]["build-args"]
    assert "org.opencontainers.image.version=" in build_step["with"]["annotations"]


def test_the_compute_tags_step_derives_stable_and_beta_channels() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    compute_step = next(s for s in steps if s.get("id") == "tags")
    script = compute_step["run"]

    assert 'channel="stable"' in script
    assert 'channel="beta"' in script
    assert 'channel="edge"' in script
    assert "echo \"channel=${channel}\" >> \"$GITHUB_OUTPUT\"" in script
