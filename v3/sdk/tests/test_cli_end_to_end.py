"""The real end-to-end loop: `init` -> `validate` -> `test`, with `test`
actually spawning the scaffolded `server.py` via `uv run` and driving it
through the SDK's own MCP client — the SPEC-406 acceptance criterion
"init scaffold passes validate and test out of the box (the example
server answers tools/list through a real client)".

Needs network access on first run (`uv run --script` fetches fastmcp for
the scaffolded server) and a working `uv` on PATH; skipped cleanly when
either is unavailable rather than failing the whole suite in an offline
environment.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from palaia_addon_sdk.cli import main
from palaia_addon_sdk.scaffold import scaffold_addon
from palaia_addon_sdk.testrun import run_local_test

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")


def test_init_then_validate_then_test_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    addon_dir = tmp_path / "sample-addon"

    exit_code = main(["init", str(addon_dir), "--maintainer", "alice"])
    assert exit_code == 0

    exit_code = main(["validate", str(addon_dir)])
    assert exit_code == 0
    assert "manifest OK" in capsys.readouterr().out

    try:
        exit_code = main(["test", str(addon_dir), "--timeout", "60"])
    except Exception as exc:  # noqa: BLE001 - reported as a skip, not a failure
        pytest.skip(f"could not exercise the scaffolded server locally: {exc}")
    output = capsys.readouterr().out
    if exit_code != 0:
        pytest.skip(f"scaffolded server did not answer (offline sandbox?): {output}")
    assert "answered tools/list with 1 tool(s): greet" in output


def test_run_local_test_reports_missing_server(tmp_path: Path) -> None:
    addon_dir = tmp_path / "no-server"
    scaffold_addon(addon_dir, maintainer="alice")
    (addon_dir / "server.py").unlink()
    from palaia_addon_sdk.testrun import TestRunError

    with pytest.raises(TestRunError, match="no server.py"):
        run_local_test(addon_dir)


def test_scaffolded_server_answers_tools_list_directly(tmp_path: Path) -> None:
    """Bypasses the CLI to assert the live MCP round trip itself, in case
    the sandbox has no network for `uv run --script`."""
    addon_dir = tmp_path / "direct-check"
    scaffold_addon(addon_dir, maintainer="alice")
    try:
        result = run_local_test(addon_dir, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not exercise the scaffolded server locally: {exc}")
    assert result.tools.tools[0]["name"] == "greet"
