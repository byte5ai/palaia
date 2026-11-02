"""Issue #544: the release gate in ``v3/tools/release_batch_gate.py``.

``v3-cut-release.yml`` runs it before it creates a tag: a v3 release comes
only from a ``main`` commit with a green ``v3-ci-batch.yml`` run whose jobs
all passed (CI standard, cost rule 12). These tests drive the script's real
decision code with GitHub API answers shaped like the real ones; the
workflow wiring itself is pinned in ``test_release_workflow.py``.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "release_batch_gate.py"
_REPO = "byte5ai/palaia"
_SHA = "0123456789abcdef0123456789abcdef01234567"


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_batch_gate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _all_green() -> dict[str, Any]:
    return {"jobs": [{"name": name, "conclusion": "success"} for name in gate.REQUIRED_JOBS]}


def _run(run_id: int, sha: str = _SHA) -> dict[str, Any]:
    return {"id": run_id, "head_sha": sha, "status": "completed", "conclusion": "success"}


def _fake_api(
    *,
    compare_status: str = "ahead",
    runs: list[dict[str, Any]] | None = None,
    jobs: dict[int, dict[str, Any]] | None = None,
) -> tuple[Callable[[str], Any], list[str]]:
    """A stand-in for ``gh api`` that answers the three paths the gate asks."""
    calls: list[str] = []

    def fetch(path: str) -> Any:
        calls.append(path)
        if path == f"repos/{_REPO}/compare/{_SHA}...main":
            return {"status": compare_status}
        if path.startswith(f"repos/{_REPO}/actions/workflows/v3-ci-batch.yml/runs?"):
            assert f"head_sha={_SHA}" in path and "status=success" in path
            return {"total_count": len(runs or []), "workflow_runs": runs or []}
        for run_id, payload in (jobs or {}).items():
            if path.startswith(f"repos/{_REPO}/actions/runs/{run_id}/jobs"):
                return payload
        raise AssertionError(f"unexpected API path {path}")

    return fetch, calls


def test_a_green_batch_on_a_main_commit_lets_the_release_through() -> None:
    fetch, _ = _fake_api(runs=[_run(41)], jobs={41: _all_green()})
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert holds, message
    assert "41" in message, "the gate names the batch run it relied on"


def test_the_tip_of_main_counts_as_on_main() -> None:
    fetch, _ = _fake_api(compare_status="identical", runs=[_run(7)], jobs={7: _all_green()})
    assert gate.check(fetch, _REPO, _SHA)[0]


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_a_commit_that_is_not_on_main_is_refused_before_any_run_is_read(status: str) -> None:
    fetch, calls = _fake_api(compare_status=status, runs=[_run(41)], jobs={41: _all_green()})
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert not holds
    assert "not on main" in message
    assert len(calls) == 1, "a branch commit must not be released even with a green batch"


def test_no_batch_run_on_the_commit_refuses_and_says_what_to_dispatch() -> None:
    fetch, _ = _fake_api(runs=[])
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert not holds
    assert "Dispatch v3-ci-batch.yml on main" in message


@pytest.mark.parametrize("conclusion", ["skipped", "failure", "cancelled", None])
def test_a_required_job_that_did_not_pass_refuses_the_release(conclusion: str | None) -> None:
    payload = _all_green()
    payload["jobs"][2]["conclusion"] = conclusion
    fetch, _ = _fake_api(runs=[_run(41)], jobs={41: payload})
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert not holds
    assert f"{gate.REQUIRED_JOBS[2]}: {conclusion}" in message


def test_a_required_job_missing_from_the_run_refuses_the_release() -> None:
    payload = _all_green()
    del payload["jobs"][0]
    fetch, _ = _fake_api(runs=[_run(41)], jobs={41: payload})
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert not holds
    assert f"{gate.REQUIRED_JOBS[0]}: not in the run" in message


def test_an_older_complete_run_on_the_same_commit_still_counts() -> None:
    incomplete = _all_green()
    incomplete["jobs"][0]["conclusion"] = "skipped"
    fetch, _ = _fake_api(runs=[_run(52), _run(41)], jobs={52: incomplete, 41: _all_green()})
    holds, message = gate.check(fetch, _REPO, _SHA)
    assert holds, message
    assert "Batch run 41" in message


def test_a_run_for_another_commit_is_never_taken() -> None:
    fetch, _ = _fake_api(runs=[_run(41, sha="f" * 40)], jobs={41: _all_green()})
    assert not gate.check(fetch, _REPO, _SHA)[0]


def test_main_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    green, _ = _fake_api(runs=[_run(41)], jobs={41: _all_green()})
    assert gate.main(["--repo", _REPO, "--sha", _SHA], fetch=green) == 0

    none, _ = _fake_api(runs=[])
    assert gate.main(["--repo", _REPO, "--sha", _SHA], fetch=none) == 1
    assert "No green v3-ci-batch.yml run" in capsys.readouterr().err

    odd, _ = _fake_api(compare_status="nonsense")
    assert gate.main(["--repo", _REPO, "--sha", _SHA], fetch=odd) == 2


def test_gh_api_reads_through_the_gh_cli_and_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real fetch shells out to ``gh api``: a fake ``gh`` on PATH proves
    the arguments and that a failing call raises instead of reading as
    "no runs"."""
    fake = tmp_path / "gh"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "api ok/path" ]; then echo \'{"status": "ahead"}\'; exit 0; fi\n'
        'echo "HTTP 404: Not Found" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    assert gate.gh_api("ok/path") == {"status": "ahead"}
    with pytest.raises(gate.GateError, match="404"):
        gate.gh_api("missing/path")
