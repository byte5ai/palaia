"""``palaia-addon`` — the add-on author's CLI: ``init``, ``validate``, ``test``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scaffold import scaffold_addon
from .testrun import TestRunError, format_preview, run_local_test
from .validate import validate_manifest


def _cmd_init(args: argparse.Namespace) -> int:
    target_dir = Path(args.directory)
    try:
        written = scaffold_addon(
            target_dir,
            addon_id=args.id,
            name=args.name,
            one_liner=args.one_liner or "Describe in one plain sentence what this add-on does.",
            maintainer=args.maintainer,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"scaffolded add-on in {target_dir}:")
    for path in written:
        print(f"  - {path}")
    print("\nnext: uv run server.py   (in another terminal, or just run `palaia-addon test`)")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    issues = validate_manifest(Path(args.target))
    for issue in issues:
        print(issue, file=sys.stderr)
    if issues:
        print(f"\n{len(issues)} problem(s)", file=sys.stderr)
        return 1
    print("manifest OK")
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    addon_dir = Path(args.directory)
    validation_issues = validate_manifest(addon_dir)
    if validation_issues:
        for issue in validation_issues:
            print(issue, file=sys.stderr)
        print(
            f"\n{len(validation_issues)} problem(s) — fix these before testing",
            file=sys.stderr,
        )
        return 1
    try:
        result = run_local_test(addon_dir, timeout=args.timeout)
    except TestRunError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(format_preview(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="palaia-addon", description="Scaffold, validate and test a palaia marketplace add-on."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="scaffold a new add-on directory")
    init.add_argument("directory", help="directory to create (or fill in)")
    init.add_argument("--id", help="add-on id (default: derived from --name or the directory name)")
    init.add_argument("--name", help="display name (default: derived from the directory name)")
    init.add_argument("--one-liner", help="one plain-language sentence describing the add-on")
    init.add_argument("--maintainer", required=True, help="your name or handle")
    init.set_defaults(func=_cmd_init)

    validate = sub.add_parser("validate", help="validate an add-on's manifest.json")
    validate.add_argument(
        "target", nargs="?", default=".", help="add-on directory, or path to manifest.json"
    )
    validate.set_defaults(func=_cmd_validate)

    test = sub.add_parser("test", help="run the add-on locally and check tools/list")
    test.add_argument("directory", nargs="?", default=".", help="add-on directory")
    test.add_argument(
        "--timeout", type=float, default=20.0, help="seconds to wait for the add-on to answer"
    )
    test.set_defaults(func=_cmd_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - hand-run entry point
    raise SystemExit(main())
