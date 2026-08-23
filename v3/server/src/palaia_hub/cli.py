"""``palaia-hub`` command-line entry point.

Currently one subcommand: ``serve``, which loads config, builds the app, and
runs it under uvicorn with graceful shutdown (uvicorn drains in-flight
requests on SIGTERM/SIGINT up to ``graceful_shutdown_timeout`` before
exiting).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .app import create_app
from .auth import TokenError, TokenStore
from .config import ConfigError, load_config
from .importers import ImportReport, ImportRunner, v2_source
from .importers import basic_memory_source as bm_source
from .vault.engine import VaultEngine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="palaia-hub")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run the hub daemon")
    serve_parser.add_argument("--host", default=None, help="Override config host")
    serve_parser.add_argument("--port", type=int, default=None, help="Override config port")

    token_parser = subparsers.add_parser("token", help="Manage MCP client tokens")
    token_subparsers = token_parser.add_subparsers(dest="token_command", required=True)

    create_parser = token_subparsers.add_parser("create", help="Issue a new client token")
    create_parser.add_argument("--name", required=True, help="Human-readable client name")
    create_parser.add_argument("--profile", required=True, help="Gateway profile path to bind to")
    create_parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        default=[],
        help="'vault:<key>:read' or 'vault:<key>:write'; repeatable",
    )

    token_subparsers.add_parser("list", help="List known tokens (no secrets shown)")

    revoke_parser = token_subparsers.add_parser("revoke", help="Revoke a token by id")
    revoke_parser.add_argument("token_id", help="Token id, from 'token list'")

    import_parser = subparsers.add_parser("import", help="Import notes from another store")
    import_subparsers = import_parser.add_subparsers(dest="import_source", required=True)

    v2_parser = import_subparsers.add_parser("v2", help="Import a palaia v2 .palaia/ store")
    v2_parser.add_argument("path", help="Path to the v2 store (.palaia/ dir, or its parent)")
    _add_import_args(v2_parser)

    bm_parser = import_subparsers.add_parser("basic-memory", help="Import a basic-memory vault")
    bm_parser.add_argument("path", help="Path to the basic-memory vault directory")
    _add_import_args(bm_parser)

    return parser


def _add_import_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vault", required=True, help="Destination v3 vault root (created if absent)"
    )
    parser.add_argument(
        "--vault-name", default="default", help="Vault name if the vault does not exist yet"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be imported without writing anything",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")


def serve(host: str | None = None, port: int | None = None) -> None:
    """Load config, build the app, and run it under uvicorn."""
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"palaia-hub: configuration error:\n{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    overrides: dict[str, object] = {}
    if host is not None:
        overrides["host"] = host
    if port is not None:
        overrides["port"] = port
    if overrides:
        config = config.model_copy(update=overrides)

    app = create_app(config, token_store=TokenStore())

    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_config=None,
        timeout_graceful_shutdown=int(config.graceful_shutdown_timeout),
    )
    server = uvicorn.Server(uvicorn_config)
    server.run()


def _token_create(name: str, profile: str, scopes: list[str]) -> None:
    store = TokenStore()
    try:
        created = store.create(name, profile, scopes)
    except TokenError as exc:
        print(f"palaia-hub: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Created token {created.info.id!r} for {name!r} (profile={profile!r}).")
    print("Copy it now — it will not be shown again:")
    print(f"  {created.token}")


def _token_list() -> None:
    store = TokenStore()
    tokens = store.list_tokens()
    if not tokens:
        print("No tokens yet. Create one with `palaia-hub token create`.")
        return
    for info in tokens:
        status = "revoked" if info.revoked_at else "active"
        print(
            f"{info.id}  {status:8}  {info.name!r}  "
            f"profile={info.profile!r}  scopes={info.scopes}"
        )


def _token_revoke(token_id: str) -> None:
    store = TokenStore()
    try:
        info = store.revoke(token_id)
    except TokenError as exc:
        print(f"palaia-hub: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Revoked token {info.id!r} ({info.name!r}).")


async def _run_v2_import(
    source_path: str, vault_root: str, vault_name: str, *, dry_run: bool
) -> ImportReport:
    engine = VaultEngine(Path(vault_root), name=vault_name)
    await engine.open()
    store_root = v2_source.find_store_root(Path(source_path))
    entries = v2_source.iter_source_entries(store_root)
    mapped = (v2_source.map_v2_entry(entry) for entry in entries)
    runner = ImportRunner(engine)
    return await runner.run("v2", str(store_root), mapped, dry_run=dry_run)


async def _run_bm_import(
    source_path: str, vault_root: str, vault_name: str, *, dry_run: bool
) -> ImportReport:
    engine = VaultEngine(Path(vault_root), name=vault_name)
    await engine.open()
    vault_path = Path(source_path)
    entries = bm_source.iter_source_entries(vault_path)
    mapped = (bm_source.map_bm_entry(entry) for entry in entries)
    runner = ImportRunner(engine)
    return await runner.run("basic-memory", str(vault_path), mapped, dry_run=dry_run)


def _print_report(report: ImportReport, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(report.summary())


def _import_v2(args: argparse.Namespace) -> None:
    report = asyncio.run(
        _run_v2_import(args.path, args.vault, args.vault_name, dry_run=args.dry_run)
    )
    _print_report(report, as_json=args.json)


def _import_basic_memory(args: argparse.Namespace) -> None:
    report = asyncio.run(
        _run_bm_import(args.path, args.vault, args.vault_name, dry_run=args.dry_run)
    )
    _print_report(report, as_json=args.json)


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(host=args.host, port=args.port)
    elif args.command == "token":
        if args.token_command == "create":
            _token_create(args.name, args.profile, args.scopes)
        elif args.token_command == "list":
            _token_list()
        elif args.token_command == "revoke":
            _token_revoke(args.token_id)
    elif args.command == "import":
        if args.import_source == "v2":
            _import_v2(args)
        elif args.import_source == "basic-memory":
            _import_basic_memory(args)


if __name__ == "__main__":
    main()
