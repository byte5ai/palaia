"""SPEC-501 deliverable #3: "SPEC-112's CI grows a channel input" — the
release workflow bakes PALAIA_CHANNEL and the
``org.opencontainers.image.version`` annotation into the pushed image, and
accepts a manual channel override. This is not something a container build
can be run against in this environment (no docker daemon), so it is
checked structurally instead: the workflow YAML actually wires what
``palaia_hub.update.check_for_update`` reads back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW_PATH = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "v3-release.yml"


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
    annotations = build_step["with"]["annotations"]
    assert "org.opencontainers.image.version=" in annotations
    # #319: buildx only annotates the OCI *index* (what the channel tag
    # resolves to) when told so explicitly via the level prefix; the
    # update check reads the index first.
    assert "index,manifest:org.opencontainers.image.version=" in annotations


def test_the_compute_tags_step_derives_stable_and_beta_channels() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    compute_step = next(s for s in steps if s.get("id") == "tags")
    script = compute_step["run"]

    assert 'channel="stable"' in script
    assert 'channel="beta"' in script
    assert 'channel="edge"' in script
    assert 'echo "channel=${channel}" >> "$GITHUB_OUTPUT"' in script


def test_the_compute_tags_step_fails_the_build_on_a_version_file_mismatch() -> None:
    """SPEC-506: a `v3.*` tag whose stripped version disagrees with
    `v3/VERSION` must fail the release build loudly, not silently publish
    an image under the wrong tag — the last-mile guard on top of
    `test_version_drift.py`'s artifact checks, which only run on the repo
    checkout, not on the tag actually being released."""
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    compute_step = next(s for s in steps if s.get("id") == "tags")
    script = compute_step["run"]

    assert "file_version=" in script
    assert "cat v3/VERSION" in script
    assert '"${version}" != "${file_version}"' in script
    assert "exit 1" in script


# ---------------------------------------------------------------------------
# Issue #386: pre-release detection. The workflows, the dry-run script and
# the drift test all used to ask "does the version contain `rc` or `beta`?"
# — so a `3.1.0-alpha1` or `3.0.1-dev1` (both valid per the drift test's own
# `_SEMVER_RE`) would have published as a non-prerelease marked "Latest",
# repointed `stable`, and baked `PALAIA_CHANNEL=stable`. SemVer says any
# `-suffix` is a pre-release; these tests pin that reading in every copy of
# the shell, and *run* the release workflow's own tag arithmetic under bash.
# ---------------------------------------------------------------------------

_V3_ROOT = Path(__file__).resolve().parents[2]
_CUT_WORKFLOW_PATH = _WORKFLOW_PATH.with_name("v3-cut-release.yml")
_DRY_RUN_PATH = _V3_ROOT / "tools" / "release-dry-run.sh"

_NEEDS_BASH = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _compute_tags_script() -> str:
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    return next(s for s in steps if s.get("id") == "tags")["run"]


def _cut_guard_script() -> str:
    workflow = yaml.safe_load(_CUT_WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["cut"]["steps"]
    return next(s for s in steps if s.get("id") == "guard")["run"]


def _run_compute_tags(
    tmp_path: Path, *, ref: str, version_file: str, channel_input: str = "none"
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run the real `Compute tags` step under bash, the way Actions would:
    `${{ github.event.inputs.channel }}` substituted, `v3/VERSION` read from
    the working directory, outputs collected from `$GITHUB_OUTPUT`."""
    script = _compute_tags_script().replace("${{ github.event.inputs.channel }}", channel_input)
    (tmp_path / "v3").mkdir(exist_ok=True)
    (tmp_path / "v3" / "VERSION").write_text(version_file + "\n", encoding="utf-8")
    output_file = tmp_path / "github_output"
    output_file.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_REF": ref,
        "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
        "GITHUB_OUTPUT": str(output_file),
        "IMAGE": "ghcr.io/byte5ai/palaia-hub",
    }
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split("=", 1)
        for line in output_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    return result, outputs


@_NEEDS_BASH
@pytest.mark.parametrize("version", ["3.0.0-rc1", "3.0.0-beta2", "3.1.0-alpha1", "3.0.1-dev1"])
def test_any_semver_suffix_publishes_to_the_beta_channel_never_stable(
    tmp_path: Path, version: str
) -> None:
    result, outputs = _run_compute_tags(
        tmp_path, ref=f"refs/tags/v3.{version}", version_file=version
    )
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "beta"
    tags = outputs["tags"].split(",")
    assert "ghcr.io/byte5ai/palaia-hub:beta" in tags
    assert "ghcr.io/byte5ai/palaia-hub:stable" not in tags
    assert f"ghcr.io/byte5ai/palaia-hub:v3.{version}" in tags
    assert outputs["annotation_version"] == version


@_NEEDS_BASH
def test_a_final_version_publishes_to_stable(tmp_path: Path) -> None:
    result, outputs = _run_compute_tags(tmp_path, ref="refs/tags/v3.3.0.0", version_file="3.0.0")
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "stable"
    tags = outputs["tags"].split(",")
    assert "ghcr.io/byte5ai/palaia-hub:stable" in tags
    assert "ghcr.io/byte5ai/palaia-hub:beta" not in tags
    assert outputs["annotation_version"] == "3.0.0"


@_NEEDS_BASH
def test_a_tag_that_disagrees_with_the_version_file_fails_the_build(tmp_path: Path) -> None:
    result, _ = _run_compute_tags(tmp_path, ref="refs/tags/v3.3.0.0", version_file="3.0.1")
    assert result.returncode != 0
    assert "does not match v3/VERSION" in result.stderr


def test_the_cut_release_guard_marks_any_suffixed_version_a_prerelease() -> None:
    script = _cut_guard_script()
    assert '"${version}" == *-*' in script
    assert "*rc*" not in script and "*beta*" not in script


def test_no_release_shell_still_detects_prereleases_by_rc_or_beta_only() -> None:
    """Every copy of the arithmetic — both workflows and the dry-run script —
    must use the same SemVer reading, or one of them silently disagrees
    with the others on the next non-rc pre-release."""
    sources = {
        "v3-release.yml": _compute_tags_script(),
        "v3-cut-release.yml": _cut_guard_script(),
        "release-dry-run.sh": _DRY_RUN_PATH.read_text(encoding="utf-8"),
    }
    for name, text in sources.items():
        assert "*rc*" not in text and "*beta*" not in text, f"{name} still tests for rc/beta"
        assert "== *-*" in text, f"{name} does not test for a SemVer suffix"


# ---------------------------------------------------------------------------
# Issue #387: the changelog-section guard. The cut workflow demanded
# `^## <version> ` (trailing space) while the dry run accepted `## <version>`
# anywhere — so a `## 3.0.0` header at end-of-line passed the dry run and
# failed the cut, and the existing `## 3.0.0-rc1` line satisfied the dry run
# for a `3.0.0` cut. Both now test `^## <version>( |$)`.
# ---------------------------------------------------------------------------

_CHANGELOG_GUARD = 'grep -qE "^## ${'


def test_cut_workflow_and_dry_run_use_the_same_changelog_header_test() -> None:
    assert f'{_CHANGELOG_GUARD}version}}( |$)"' in _cut_guard_script()
    assert f'{_CHANGELOG_GUARD}VERSION}}( |$)"' in _DRY_RUN_PATH.read_text(encoding="utf-8")


@_NEEDS_BASH
@pytest.mark.parametrize(
    ("changelog", "accepted"),
    [
        ("## 3.0.0 — 2026-09-15\n", True),
        ("## 3.0.0\n", True),
        ("## 3.0.0-rc1 — 2026-09-01\n", False),
        ("### 3.0.0\n", False),
        ("see ## 3.0.0 below\n", False),
    ],
)
def test_the_changelog_header_test_accepts_exactly_the_documented_forms(
    tmp_path: Path, changelog: str, accepted: bool
) -> None:
    """RELEASING.md §3 states the header form; this runs the guards' own
    `grep` against each documented case, so the doc, the cut and the dry
    run cannot drift apart again."""
    path = tmp_path / "CHANGELOG.md"
    path.write_text(changelog, encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", f'grep -qE "^## ${{version}}( |$)" "{path}"'],
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "version": "3.0.0"},
        check=False,
    )
    assert (result.returncode == 0) is accepted


# ---------------------------------------------------------------------------
# Issue #392: the v3 CI's path filter. This file and `test_pi_image.py` pin
# the v3 workflows' structure, but `v3-ci.yml` ran only for `v3/**` — a PR
# editing just `.github/workflows/v3-*.yml` got no v3 CI at all.
# ---------------------------------------------------------------------------

_CI_WORKFLOW_PATH = _WORKFLOW_PATH.with_name("v3-ci.yml")


@pytest.mark.parametrize("trigger", ["push", "pull_request"])
def test_v3_ci_runs_for_changes_to_the_v3_workflow_files_themselves(trigger: str) -> None:
    workflow = yaml.safe_load(_CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    paths = workflow[True][trigger]["paths"]
    assert "v3/**" in paths
    assert ".github/workflows/v3-*.yml" in paths, (
        f"v3-ci.yml `{trigger}.paths` must include the v3 workflow files, or a PR "
        "touching only them runs no v3 CI (issue #392)"
    )


# ---------------------------------------------------------------------------
# Issue #393: the manual `channel` input. Dispatching on `main` with
# `channel=stable` tagged `stable` and baked `PALAIA_CHANNEL=stable` for a
# build whose version annotation is `0.0.0+edge.<sha>` and which no
# `v3.<version>` tag names — every stable hub would then compare against
# `0.0.0` and report "up to date" until the next real tag.
# ---------------------------------------------------------------------------


@_NEEDS_BASH
@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_a_manual_channel_is_refused_on_a_branch_ref(tmp_path: Path, channel: str) -> None:
    result, outputs = _run_compute_tags(
        tmp_path, ref="refs/heads/main", version_file="3.0.0", channel_input=channel
    )
    assert result.returncode != 0
    assert "only honoured on a v3.* release tag" in result.stderr
    assert "tags" not in outputs, "the step must fail before it emits tags"


@_NEEDS_BASH
def test_a_manual_channel_is_honoured_on_a_release_tag(tmp_path: Path) -> None:
    result, outputs = _run_compute_tags(
        tmp_path, ref="refs/tags/v3.3.0.0-rc1", version_file="3.0.0-rc1", channel_input="stable"
    )
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "stable"
    assert "ghcr.io/byte5ai/palaia-hub:stable" in outputs["tags"].split(",")
    assert outputs["annotation_version"] == "3.0.0-rc1"


@_NEEDS_BASH
def test_a_plain_manual_rebuild_on_main_still_works(tmp_path: Path) -> None:
    result, outputs = _run_compute_tags(
        tmp_path, ref="refs/heads/main", version_file="3.0.0", channel_input="none"
    )
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "edge"
    assert "ghcr.io/byte5ai/palaia-hub:edge" in outputs["tags"].split(",")
