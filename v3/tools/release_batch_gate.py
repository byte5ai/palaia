#!/usr/bin/env python3
"""Release gate: a v3 release comes only from a `main` commit with a green batch.

`v3-cut-release.yml` runs this before it creates a tag (issue #544, CI
standard cost rule 12). Pull requests run only the light checks
(`v3-ci.yml`); the full suite, the e2e scenarios, the builds and the bundle
signing run in `v3-ci-batch.yml`, dispatched on `main` after a series of
merges. This script proves, through the GitHub API, that

1. the commit being released is on `main`, and
2. a `v3-ci-batch.yml` run on exactly that commit concluded `success` with
   every job in :data:`REQUIRED_JOBS` successful — not skipped, not just
   "some green run".

It starts no batch: if there is none, it fails and says what to dispatch.

Usage (in the workflow, with ``GH_TOKEN`` set)::

    python3 v3/tools/release_batch_gate.py --repo "$GITHUB_REPOSITORY" --sha "$GITHUB_SHA"

Exit 0 when the gate holds, 1 when it does not, 2 on an API/usage error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

BATCH_WORKFLOW = "v3-ci-batch.yml"

# Every job `v3-ci-batch.yml` runs. A release needs all of them green.
# server/tests/test_release_workflow.py pins this tuple to the jobs the batch
# workflow actually defines, so a job added there cannot be forgotten here.
REQUIRED_JOBS: tuple[str, ...] = (
    "python",
    "sdk",
    "e2e",
    "mcpb",
    "web",
    "docs-site",
    "dependency-audit",
)

Fetch = Callable[[str], Any]


class GateError(Exception):
    """The gate could not be evaluated (API error, unexpected answer)."""


def gh_api(path: str) -> Any:
    """GET one GitHub API path through the `gh` CLI (auth from ``GH_TOKEN``)."""
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(f"gh api {path} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def commit_is_on_main(fetch: Fetch, repo: str, sha: str) -> bool:
    """True when `sha` is `main` or an ancestor of it.

    The compare API answers how `main` relates to `sha`: `identical` or
    `ahead` (main has `sha` plus later commits) means `sha` is on main;
    `behind` or `diverged` means it is not.
    """
    status = fetch(f"repos/{repo}/compare/{sha}...main").get("status")
    if status not in {"identical", "ahead", "behind", "diverged"}:
        raise GateError(f"unexpected compare status {status!r} for {sha}...main")
    return status in {"identical", "ahead"}


def job_conclusions(jobs_payload: Mapping[str, Any]) -> dict[str, str | None]:
    return {job["name"]: job.get("conclusion") for job in jobs_payload.get("jobs", [])}


def missing_or_red(conclusions: Mapping[str, str | None], required: Sequence[str]) -> list[str]:
    """Required jobs that are absent or did not conclude `success`."""
    problems = []
    for name in required:
        if name not in conclusions:
            problems.append(f"{name}: not in the run")
        elif conclusions[name] != "success":
            problems.append(f"{name}: {conclusions[name]}")
    return problems


def find_green_batch(
    fetch: Fetch, repo: str, sha: str, required: Sequence[str] = REQUIRED_JOBS
) -> tuple[int | None, list[str]]:
    """The newest successful batch run on `sha` whose required jobs all passed.

    Returns ``(run_id, [])`` when one exists, otherwise ``(None, reasons)``.
    """
    runs = fetch(
        f"repos/{repo}/actions/workflows/{BATCH_WORKFLOW}/runs"
        f"?head_sha={sha}&status=success&per_page=20"
    ).get("workflow_runs", [])
    reasons: list[str] = []
    for run in runs:
        if run.get("head_sha") != sha or run.get("conclusion") != "success":
            continue
        conclusions = job_conclusions(
            fetch(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")
        )
        problems = missing_or_red(conclusions, required)
        if not problems:
            return run["id"], []
        reasons.append(f"run {run['id']}: " + ", ".join(problems))
    if not reasons:
        reasons.append(f"no successful {BATCH_WORKFLOW} run on {sha}")
    return None, reasons


def check(fetch: Fetch, repo: str, sha: str) -> tuple[bool, str]:
    """Evaluate the whole gate; returns ``(holds, message)``."""
    if not commit_is_on_main(fetch, repo, sha):
        return False, (
            f"{sha} is not on main. A v3 release is cut only from a main commit "
            "(v3/RELEASING.md §3)."
        )
    run_id, reasons = find_green_batch(fetch, repo, sha)
    if run_id is None:
        return False, (
            f"No green {BATCH_WORKFLOW} run on {sha}: "
            + "; ".join(reasons)
            + f". Dispatch {BATCH_WORKFLOW} on main, wait until it is green, "
            "then cut again (v3/RELEASING.md §3)."
        )
    return True, (
        f"Batch run {run_id} on {sha} is green: all {len(REQUIRED_JOBS)} required jobs "
        f"passed (https://github.com/{repo}/actions/runs/{run_id})."
    )


def main(argv: Sequence[str] | None = None, fetch: Fetch = gh_api) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--sha", required=True, help="the commit to release")
    args = parser.parse_args(argv)
    try:
        holds, message = check(fetch, args.repo, args.sha)
    except GateError as exc:
        print(f"release gate could not be evaluated: {exc}", file=sys.stderr)
        return 2
    print(message, file=sys.stdout if holds else sys.stderr)
    return 0 if holds else 1


if __name__ == "__main__":
    sys.exit(main())
