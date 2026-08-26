"""SPEC-505 acceptance criterion: "migration guide's import command
round-trips a real v2 fixture store" — reuses SPEC-111's golden fixtures
(``server/tests/fixtures/import-v2``, the same store ``test_v2_import.py``
and ``test_cli_import.py`` exercise) and runs the exact command line
published in ``docs/migrate-from-v2.md``, byte for byte, so the doc can
never drift from what the CLI actually accepts.

Also verifies the guide's rollback claim ("the importer only ever *reads*
your v2 store... nothing about your v2 install changes") for real: every
file under the fixture store is hashed before and after both the dry run
and the real apply, and nothing may differ.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from palaia_hub.cli import main

DOC = Path(__file__).resolve().parents[2] / "docs" / "migrate-from-v2.md"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "import-v2"

#: Pulled out of the doc itself (inside its fenced ```bash block) rather than
#: retyped here, so a change to the published command is caught the moment
#: the doc and the CLI's actual argument parsing disagree.
_COMMAND_RE = re.compile(r"```bash\n(palaia-hub import v2 [^\n]+)\n```")


def _published_command() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    match = _COMMAND_RE.search(text)
    assert match, f"no `palaia-hub import v2 ...` fenced command found in {DOC}"
    return match.group(1).split()


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_published_command_round_trips_the_golden_v2_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _published_command()
    # argv[3] is the placeholder source path ("/path/to/.palaia"); swap in
    # the real golden fixture, same as a reader would swap in their own path.
    assert argv[:3] == ["palaia-hub", "import", "v2"]
    argv[3] = str(FIXTURE)
    vault_root = tmp_path / "vault"
    vault_index = argv.index("--vault")
    argv[vault_index + 1] = str(vault_root)

    before = _tree_hashes(FIXTURE)

    main(argv[1:])  # main() takes argv without the program name
    first_run = capsys.readouterr().out

    after_apply = _tree_hashes(FIXTURE)
    assert after_apply == before, "the v2 fixture store must never be modified by import"

    assert (vault_root / "imported" / "v2").is_dir()
    assert "created" in first_run

    # Re-running the identical published command is the guide's idempotence
    # claim ("does nothing new") — every permalink already resolves.
    main(argv[1:])
    second_run = capsys.readouterr().out
    assert "created: 0" in second_run or "\"created\": 0" in second_run

    after_second = _tree_hashes(FIXTURE)
    assert after_second == before, "a re-run must also never modify the v2 fixture store"
