"""SPEC-501 deliverable #3: "SPEC-112's CI grows a channel input" — the
release workflow bakes PALAIA_CHANNEL and the
``org.opencontainers.image.version`` annotation into the pushed image, and
accepts a manual channel override. This is not something a container build
can be run against in this environment (no docker daemon), so it is
checked structurally instead: the workflow YAML actually wires what
``palaia_hub.update.check_for_update`` reads back.
"""

from __future__ import annotations

import importlib.util
import os
import shlex
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
        "IMAGE": "ghcr.io/byte5ai/palaia",
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
    assert "ghcr.io/byte5ai/palaia:beta" in tags
    assert "ghcr.io/byte5ai/palaia:stable" not in tags
    assert f"ghcr.io/byte5ai/palaia:v3.{version}" in tags
    # Issue #394: Home Assistant pulls `image:<config.yaml version>`.
    assert f"ghcr.io/byte5ai/palaia:{version}" in tags
    assert outputs["annotation_version"] == version


@_NEEDS_BASH
def test_a_final_version_publishes_to_stable(tmp_path: Path) -> None:
    result, outputs = _run_compute_tags(tmp_path, ref="refs/tags/v3.3.0.0", version_file="3.0.0")
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "stable"
    tags = outputs["tags"].split(",")
    assert "ghcr.io/byte5ai/palaia:stable" in tags
    assert "ghcr.io/byte5ai/palaia:beta" not in tags
    assert "ghcr.io/byte5ai/palaia:3.0.0" in tags
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
#
# Issue #487: that filter moved from the workflow trigger into the `changes`
# job, so the workflow always runs and its `v3-ci-required` gate always
# reports — the one check `main` requires. A workflow-level filter would
# leave a root-only PR waiting forever on a check that never runs.
# ---------------------------------------------------------------------------

_CI_WORKFLOW_PATH = _WORKFLOW_PATH.with_name("v3-ci.yml")
_BATCH_WORKFLOW_PATH = _WORKFLOW_PATH.with_name("v3-ci-batch.yml")
_CI_GATE_JOB = "required"


def _load_ci_workflow() -> dict:
    return yaml.safe_load(_CI_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _ci_filters(workflow: dict) -> dict:
    steps = workflow["jobs"]["changes"]["steps"]
    step = next(s for s in steps if s.get("id") == "filter")
    return yaml.safe_load(step["with"]["filters"])


def test_v3_ci_runs_on_every_pull_request_and_nothing_else() -> None:
    """Issue #544: the light checks run once per change — on the PR, not again
    on the push of the merge (CI standard, cost rule 13). No `branches:`
    filter (stacked PRs get checks too, trigger rule 1) and no workflow-level
    path filter: the required gate would then never report on PRs outside
    the filter (issue #487). Lanes are gated through the `changes` job."""
    on = _load_ci_workflow()[True]
    assert set(on) == {"pull_request"}, f"v3-ci.yml triggers on {sorted(on)}"
    pull_request = on["pull_request"] or {}
    for key in ("branches", "branches-ignore", "paths", "paths-ignore", "types"):
        assert key not in pull_request, f"v3-ci.yml `pull_request` must not set `{key}`"


def test_v3_ci_runs_for_changes_to_the_v3_workflow_files_themselves() -> None:
    workflow = _load_ci_workflow()
    python = workflow["jobs"]["python"]
    assert python["needs"] == "changes"
    assert "needs.changes.outputs.v3 == 'true'" in python["if"]
    v3 = _ci_filters(workflow)["v3"]
    assert "v3/**" in v3
    assert ".github/workflows/v3-*.yml" in v3, (
        "the `v3` filter that gates the python lane must include the v3 workflow "
        "files, or a PR touching only them runs no v3 tests (issue #392)"
    )


def test_the_v3_ci_gate_needs_every_lane_and_always_reports() -> None:
    jobs = _load_ci_workflow()["jobs"]
    gate = jobs[_CI_GATE_JOB]
    assert gate["name"] == "v3-ci-required", (
        "the gate's name is the check `main` requires — renaming it silently "
        "un-requires CI until branch protection is updated (issue #487)"
    )
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == set(jobs) - {_CI_GATE_JOB}, (
        "every v3-ci.yml job must be in the gate's `needs`, or a failing lane "
        "no longer blocks the merge (issue #487)"
    )
    script = " ".join(step.get("run", "") + str(step.get("env", "")) for step in gate["steps"])
    assert "contains(needs.*.result, 'failure')" in script
    assert "contains(needs.*.result, 'cancelled')" in script


# ---------------------------------------------------------------------------
# Issue #544: light checks on the PR, heavy work in a dispatched batch, and a
# release only from a `main` commit with a green batch (CI standard, cost
# rules 9, 12, 13; test rule 5).
# ---------------------------------------------------------------------------


def _load_batch_workflow() -> dict:
    return yaml.safe_load(_BATCH_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _runs(workflow: dict, job: str) -> list[str]:
    return [step["run"] for step in workflow["jobs"][job]["steps"] if "run" in step]


def _all_runs(workflow: dict) -> str:
    return "\n".join(run for job in workflow["jobs"] for run in _runs(workflow, job))


def test_the_batch_is_dispatch_only() -> None:
    on = _load_batch_workflow()[True]
    assert set(on) == {"workflow_dispatch"}, (
        f"v3-ci-batch.yml must start only by dispatch, not on {sorted(on)} "
        "(no heavy CI on push/PR, no schedule)"
    )


def test_heavy_work_stays_off_the_pull_request_workflow() -> None:
    """What builds, packs, signs, audits or starts real hubs belongs to the
    batch. A step copied back into v3-ci.yml turns this red."""
    runs = _all_runs(_load_ci_workflow())
    assert "npm run build" not in runs, "builds run in v3-ci-batch.yml"
    assert "pip-audit" not in runs and "npm audit" not in runs, "audits run in the batch"
    pytest_calls = [line for line in runs.splitlines() if "pytest" in line]
    assert pytest_calls, "the PR workflow must still run tests"
    for call in pytest_calls:
        targets = [t for t in shlex.split(call) if t.startswith("server/tests/e2e")]
        assert not targets, f"the e2e scenarios run in the batch, not on the PR: {call}"
    server_calls = [call for call in pytest_calls if "--ignore=server/tests/e2e" in call]
    assert server_calls, "the python lane runs the server suite"
    for call in server_calls:
        assert '-m "not integration"' in call, (
            "the PR lane runs the server suite without the `integration` tests"
        )


def test_the_batch_runs_everything_the_pull_request_leaves_out() -> None:
    """The other half of the split: nothing moved off the PR is dropped."""
    batch = _load_batch_workflow()
    assert "uv run pytest server/tests/e2e" in "\n".join(_runs(batch, "e2e"))
    full = [r for r in _runs(batch, "python") if "pytest" in r]
    assert full and all("-m " not in r for r in full), "the batch runs the full server suite"
    for job in ("web", "docs-site", "mcpb"):
        assert "npm run build" in "\n".join(_runs(batch, job)), f"batch `{job}` must build"
    audits = "\n".join(_runs(batch, "dependency-audit"))
    assert "pip-audit" in audits and "npm audit" in audits and "uv lock --check" in audits


def test_the_pull_request_lane_still_gates_the_lockfile() -> None:
    assert "uv lock --check" in "\n".join(_runs(_load_ci_workflow(), "python"))


def test_the_integration_marker_is_registered_and_used() -> None:
    """The PR lane deselects `integration`; an unregistered marker or one no
    test carries would make that selection meaningless."""
    config = (_V3_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"integration:' in config, "register the marker in v3/pyproject.toml"
    tests = _V3_ROOT / "server" / "tests"
    marked = [p for p in tests.rglob("test_*.py") if "pytest.mark.integration" in p.read_text()]
    assert marked, "no test carries the `integration` marker"


def test_pr_runs_cancel_superseded_runs_and_the_batch_never_does() -> None:
    assert _load_ci_workflow()["concurrency"]["cancel-in-progress"] is True
    assert _load_batch_workflow()["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("path", [_CI_WORKFLOW_PATH, _BATCH_WORKFLOW_PATH], ids=lambda p: p.name)
def test_every_v3_ci_job_has_a_hang_timeout(path: Path) -> None:
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    missing = [name for name, job in jobs.items() if "timeout-minutes" not in job]
    assert not missing, f"{path.name}: jobs without timeout-minutes: {missing}"


def test_the_release_gate_requires_every_batch_job() -> None:
    spec = importlib.util.spec_from_file_location(
        "release_batch_gate", _V3_ROOT / "tools" / "release_batch_gate.py"
    )
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    jobs = _load_batch_workflow()["jobs"]
    names = {job.get("name", key) for key, job in jobs.items()}
    assert set(gate.REQUIRED_JOBS) == names, (
        "release_batch_gate.REQUIRED_JOBS must list exactly the jobs of v3-ci-batch.yml"
    )
    assert gate.BATCH_WORKFLOW == _BATCH_WORKFLOW_PATH.name


def test_the_cut_checks_the_batch_before_it_creates_anything() -> None:
    steps = _cut_workflow()["jobs"]["cut"]["steps"]
    names = [s.get("name", "") for s in steps]
    gate_index = next(i for i, s in enumerate(steps) if "release_batch_gate.py" in s.get("run", ""))
    assert gate_index < names.index("Create tag + release")
    gate_step = steps[gate_index]
    assert gate_step["if"] == "steps.guard.outputs.create == 'true'"
    assert gate_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert '--sha "${GITHUB_SHA}"' in gate_step["run"]
    assert '--repo "${GITHUB_REPOSITORY}"' in gate_step["run"]


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
    assert "ghcr.io/byte5ai/palaia:stable" in outputs["tags"].split(",")
    assert outputs["annotation_version"] == "3.0.0-rc1"


@_NEEDS_BASH
def test_a_plain_manual_rebuild_on_main_still_works(tmp_path: Path) -> None:
    result, outputs = _run_compute_tags(
        tmp_path, ref="refs/heads/main", version_file="3.0.0", channel_input="none"
    )
    assert result.returncode == 0, result.stderr
    assert outputs["channel"] == "edge"
    assert "ghcr.io/byte5ai/palaia:edge" in outputs["tags"].split(",")


# ---------------------------------------------------------------------------
# Issue #400: the arm64 smoke boots the image under the documented hardening
# flags, so the hardened posture is proven on both architectures.
# ---------------------------------------------------------------------------


def test_the_arm64_smoke_runs_under_the_documented_hardening_flags() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-and-push"]["steps"]
    smoke = next(s for s in steps if "arm64 smoke" in s.get("name", ""))
    script = smoke["run"]
    for flag in (
        "--security-opt no-new-privileges:true",
        "--cap-drop ALL",
        "--read-only",
        "--tmpfs /tmp",
    ):
        assert flag in script, f"the arm64 smoke lacks {flag}"


# ---------------------------------------------------------------------------
# Issue #401: release-workflow robustness.
# ---------------------------------------------------------------------------


def _cut_workflow() -> dict:
    return yaml.safe_load(_CUT_WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_the_release_title_reaches_the_shell_through_the_environment() -> None:
    steps = _cut_workflow()["jobs"]["cut"]["steps"]
    create = next(s for s in steps if s.get("name") == "Create tag + release")
    assert "${{ steps.guard.outputs.title }}" not in create["run"]
    assert create["env"]["TITLE"] == "${{ steps.guard.outputs.title }}"
    assert '--title "${TITLE}"' in create["run"]
    assert create["if"] == "steps.guard.outputs.create == 'true'"


def test_the_cut_offers_a_redispatch_only_recovery() -> None:
    workflow = _cut_workflow()
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert inputs["redispatch_only"]["type"] == "boolean"
    assert inputs["redispatch_only"]["default"] is False
    assert "redispatch_only=true" in _cut_guard_script()


@pytest.mark.parametrize("path", [_CI_WORKFLOW_PATH, _BATCH_WORKFLOW_PATH], ids=lambda p: p.name)
def test_ci_runs_the_sdk_tests_and_its_own_mypy(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    sdk = workflow["jobs"]["sdk"]
    assert sdk["defaults"]["run"]["working-directory"] == "v3/sdk"
    runs = [s.get("run", "") for s in sdk["steps"]]
    assert any("uv run mypy src" in run for run in runs)
    assert any("uv run pytest" in run for run in runs)


def test_dependency_audits_report_into_the_job_summary() -> None:
    workflow = yaml.safe_load(_BATCH_WORKFLOW_PATH.read_text(encoding="utf-8"))
    audits = [
        s
        for s in workflow["jobs"]["dependency-audit"]["steps"]
        if "advisories" in s.get("name", "")
    ]
    assert len(audits) == 4
    for step in audits:
        assert step["continue-on-error"] is True, "reporting, not gating — by design"
        assert "report-audit.sh" in step["run"]
    script = (_WORKFLOW_PATH.parents[1] / "scripts" / "report-audit.sh").read_text(encoding="utf-8")
    assert "GITHUB_STEP_SUMMARY" in script
    assert "::warning" in script


# ---------------------------------------------------------------------------
# Issue #405: CI/build time.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [_CI_WORKFLOW_PATH, _BATCH_WORKFLOW_PATH], ids=lambda p: p.name)
def test_every_uv_setup_in_ci_caches_its_environment(path: Path) -> None:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    setups = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv")
    ]
    assert len(setups) >= 2
    for step in setups:
        assert step["with"]["enable-cache"] is True
        assert step["with"]["cache-dependency-glob"].endswith("uv.lock")


def test_a_merge_to_main_starts_no_image_build() -> None:
    """A multi-arch build + push + QEMU smoke is the expensive kind of run;
    it happens for a release tag or a deliberate dispatch, never per merge
    (owner rule: no heavy CI on push). `edge` is built by a dispatch on
    `main` — see `test_a_plain_manual_rebuild_on_main_still_works`."""
    on = _load_workflow()[True]
    assert set(on) == {"push", "workflow_dispatch"}
    assert set(on["push"]) == {"tags"}, "push may trigger on release tags only"
    assert on["push"]["tags"] == ["v3.*"]


def test_the_dockerfile_installs_dependencies_before_the_project_sources() -> None:
    lines = (_V3_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8").splitlines()
    no_project = next(i for i, line in enumerate(lines) if "--no-install-project" in line)
    sources = next(i for i, line in enumerate(lines) if line.startswith("COPY v3/server/ "))
    full_sync = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("RUN uv sync") and "--no-install-project" not in line
    )
    assert no_project < sources < full_sync


def _install_flags(command: str) -> tuple[str, frozenset[str]]:
    """``--package`` and the set of ``--extra`` values of a uv command."""
    words = shlex.split(command.replace("\\\n", " "))
    package = words[words.index("--package") + 1]
    extras = frozenset(words[i + 1] for i, word in enumerate(words) if word == "--extra")
    return package, extras


def test_the_runtime_audit_checks_what_the_image_installs() -> None:
    """Issue #626: python-zeroconf was installed with ``uv pip install``,
    outside the lockfile, so the batch's runtime audit never saw it. Every
    Python package in the image now comes from ``uv sync`` against the
    lockfile, and the audit exports the same package with the same extras."""
    dockerfile = (_V3_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install" not in dockerfile, "the image installs a package outside the lockfile"

    syncs = {
        _install_flags(line) for line in dockerfile.splitlines() if line.startswith("RUN uv sync")
    }
    assert len(syncs) == 1, f"the image's uv sync steps disagree: {syncs}"

    jobs = yaml.safe_load(_BATCH_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    exports = [
        step["run"]
        for job in jobs.values()
        for step in job.get("steps", [])
        if "uv export" in step.get("run", "") and "--no-dev" in step["run"]
    ]
    assert len(exports) == 1, "expected exactly one runtime export in v3-ci-batch.yml"
    (export,) = exports
    export_command = export[export.index("uv export") :].split("-o ")[0]
    assert {_install_flags(export_command)} == syncs


_WORKFLOWS_DIR = _WORKFLOW_PATH.parent
#: Every workflow the v3 line runs (v3-*.yml) plus the track-label workflow
#: that labels v3 items; ci.yml and publish.yml are v2's and out of scope.
_V3_RUNNER_WORKFLOWS = sorted(
    [*_WORKFLOWS_DIR.glob("v3-*.yml"), _WORKFLOWS_DIR / "track-label.yml"]
)


@pytest.mark.parametrize("path", _V3_RUNNER_WORKFLOWS, ids=lambda p: p.name)
def test_every_v3_workflow_job_pins_its_runner_image(path: Path) -> None:
    """A ``*-latest`` runner silently moves to a new OS (ubuntu-latest became
    Ubuntu 26.04 and dropped `qemu-user-static`, which broke the rc7 Pi image
    build). The CI standard (CI001) pins the image instead."""
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    floating = {
        name: job.get("runs-on")
        for name, job in jobs.items()
        if "-latest" in str(job.get("runs-on", ""))
    }
    assert not floating, f"{path.name}: jobs on a floating runner image: {floating}"
