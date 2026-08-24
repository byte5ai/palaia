"""``palaia-hub`` command-line entry point.

Currently one subcommand: ``serve``, which loads config, builds the app, and
runs it under uvicorn with graceful shutdown (uvicorn drains in-flight
requests on SIGTERM/SIGINT up to ``graceful_shutdown_timeout`` before
exiting).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from .auth import TokenError, TokenStore
from .config import ConfigError, HubConfig, load_config, palaia_home
from .importers import ImportReport, ImportRunner, v2_source
from .importers import basic_memory_source as bm_source
from .index import VaultIndex, embed_progress
from .oauth import (
    AuthorizationServer,
    OAuthError,
    OAuthStore,
    ResourceRegistry,
    now_seconds,
    provision_machine_client,
    set_owner_password,
)
from .serve import build_production_app
from .vault import EventBus, VaultRegistry
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

    _add_oauth_parser(subparsers)

    import_parser = subparsers.add_parser("import", help="Import notes from another store")
    import_subparsers = import_parser.add_subparsers(dest="import_source", required=True)

    v2_parser = import_subparsers.add_parser("v2", help="Import a palaia v2 .palaia/ store")
    v2_parser.add_argument("path", help="Path to the v2 store (.palaia/ dir, or its parent)")
    _add_import_args(v2_parser)

    bm_parser = import_subparsers.add_parser("basic-memory", help="Import a basic-memory vault")
    bm_parser.add_argument("path", help="Path to the basic-memory vault directory")
    _add_import_args(bm_parser)

    return parser


def _add_oauth_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The ``palaia-hub oauth ...`` admin surface (SPEC-203).

    Deliberately CLI-only, not REST: setting the owner password and minting a
    machine identity change who can reach the hub, and MASTERPLAN §5.7 keeps
    "decisions that change the attack surface" off the chat/app surfaces. The
    dashboard's read-only client list is a later SPEC's job.
    """
    oauth_parser = subparsers.add_parser("oauth", help="Manage the OAuth 2.1 server")
    oauth_subparsers = oauth_parser.add_subparsers(dest="oauth_command", required=True)

    password_parser = oauth_subparsers.add_parser(
        "set-password", help="Create or replace the local owner account"
    )
    password_parser.add_argument("--username", required=True, help="Owner account username")

    machine_parser = oauth_subparsers.add_parser(
        "machine-client",
        help="Provision a machine client (client_credentials, pinned audience)",
    )
    machine_parser.add_argument("--name", required=True, help="Human-readable client name")
    machine_parser.add_argument(
        "--profile", required=True, help="MCP profile path this client is pinned to"
    )
    machine_parser.add_argument(
        "--scope",
        dest="scopes",
        action="append",
        default=[],
        help="'vault:<key>:read' or 'vault:<key>:write'; repeatable",
    )

    oauth_subparsers.add_parser("clients", help="List registered clients (no secrets shown)")
    oauth_subparsers.add_parser("gc", help="Prune orphaned registered clients now")


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

    asyncio.run(_serve_async(config))


async def _serve_async(config: HubConfig) -> None:
    """Build the production app and serve it under uvicorn's async server.

    A separate ``asyncio.run`` boundary from ``uvicorn.Server.run()`` would
    mean two event loops (one to await :func:`build_production_app`'s
    vault/index opens, a second uvicorn starts internally) — using
    ``server.serve()`` directly inside this coroutine keeps everything on
    one loop, which is what lets a vault created at runtime (SPEC-210)
    actually reach the same :class:`~palaia_hub.gateway.dynamic.DynamicGateway`
    instance this function built.
    """
    production = await build_production_app(config, oauth_server=_maybe_oauth_server(config))
    uvicorn_config = uvicorn.Config(
        production.app,
        host=config.host,
        port=config.port,
        log_config=None,
        timeout_graceful_shutdown=int(config.graceful_shutdown_timeout),
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


def _profile_scopes(profiles: Sequence[str], vault_keys: Sequence[str]) -> dict[str, list[str]]:
    """``{profile: grantable scopes}`` for every profile, over ``vault_keys``.

    Until the gateway's own config reaches ``config.yaml`` (see
    ``OAuthSettings.profiles``), the scope ceiling is derived from the vault
    registry: every registered vault contributes a read and a write scope.
    That is the same vocabulary SPEC-108 tokens use
    (:func:`palaia_hub.auth.scopes.vault_scope`), so a client's scopes mean
    the same thing whichever credential carried them.
    """
    scopes = [scope for key in vault_keys for scope in (f"vault:{key}:read", f"vault:{key}:write")]
    return {profile: list(scopes) for profile in profiles}


def _maybe_oauth_server(config: HubConfig) -> AuthorizationServer | None:
    """Build the authorization server if config asks for one; else ``None``."""
    if not config.oauth.enabled:
        return None
    if not config.oauth.issuer:
        print(
            "palaia-hub: oauth.enabled is true but oauth.issuer is not set. Fix: set "
            "`oauth.issuer` in config.yaml to the public https URL clients reach this "
            "hub at.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    vault_keys = sorted(VaultRegistry().names())
    profiles = config.oauth.profiles
    if not profiles:
        print(
            "palaia-hub: oauth.enabled is true but oauth.profiles is empty, so no MCP "
            "resource can be named in a token. Fix: list your gateway's profile paths "
            "under `oauth.profiles` in config.yaml.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    server = AuthorizationServer.build(config, _profile_scopes(profiles, vault_keys))
    print(
        f"OAuth 2.1 authorization server enabled (issuer {server.issuer}); "
        f"profiles: {', '.join(profiles)}"
    )
    return server


def _oauth_server_for_admin() -> tuple[OAuthStore, HubConfig]:
    """Open the OAuth store for a CLI admin command, without an HTTP surface."""
    config = load_config()
    store = OAuthStore(palaia_home())
    store.open()
    return store, config


def _oauth_set_password(username: str) -> None:
    store, _config = _oauth_server_for_admin()
    password = getpass.getpass("New owner password: ")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        print("palaia-hub: the two passwords do not match.", file=sys.stderr)
        raise SystemExit(1)
    try:
        set_owner_password(store, username, password, now=now_seconds())
    except OAuthError as exc:
        print(f"palaia-hub: {exc.description}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Owner account set for {username!r}. Existing login sessions were cleared.")


def _oauth_machine_client(name: str, profile: str, scopes: list[str]) -> None:
    store, config = _oauth_server_for_admin()
    if not config.oauth.issuer:
        print(
            "palaia-hub: oauth.issuer is not set, so a machine client cannot be "
            "pinned to a resource. Fix: set `oauth.issuer` in config.yaml.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    registry = ResourceRegistry(config.oauth.issuer, config.oauth.profiles or [profile])
    try:
        audience = registry.audience(profile)
        provisioned = provision_machine_client(
            store, client_name=name, audience=audience, scopes=scopes, now=now_seconds()
        )
    except (KeyError, OAuthError) as exc:
        print(f"palaia-hub: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"Provisioned machine client {provisioned.client.client_id!r} for {audience}.")
    print("Copy the secret now — it will not be shown again:")
    print(f"  {provisioned.client_secret}")


def _oauth_clients() -> None:
    store, _config = _oauth_server_for_admin()
    clients = store.list_clients()
    if not clients:
        print("No registered OAuth clients yet.")
        return
    for client in clients:
        kind = "machine" if client.is_machine else client.source
        print(
            f"{client.client_id}  {kind:8}  {client.client_name!r}  "
            f"scopes={list(client.scopes)}"
        )


def _oauth_gc() -> None:
    store, config = _oauth_server_for_admin()
    report = store.prune_clients(
        now=now_seconds(),
        ttl_seconds=config.oauth.client_gc_ttl,
        throttle_seconds=config.oauth.client_gc_interval,
        force=True,
    )
    print(
        f"Pruned {report.pruned_count} orphaned client(s); kept "
        f"{report.kept_machine} machine and {report.kept_active} active client(s)."
    )


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


async def _open_engine_and_index(
    vault_root: str, vault_name: str, *, dry_run: bool
) -> tuple[VaultEngine, VaultIndex | None]:
    """Open the destination engine and, for a real (non-dry-run) import, its
    index too — so imported notes actually reach the SPEC-104 embed backlog
    (SPEC-210 deliverable #2) instead of only ever being written to files.

    ``dry_run`` skips the index entirely: nothing is written, so there is
    nothing to index either, and a dry run must never create a
    ``.palaia/index.db`` as a side effect.
    """
    engine = VaultEngine(Path(vault_root), name=vault_name, bus=EventBus())
    await engine.open()
    if dry_run:
        return engine, None
    index = VaultIndex(engine)
    await index.open()
    return engine, index


async def _index_status_line(index: VaultIndex | None) -> str | None:
    """The embed-progress summary for a just-finished import, or ``None``
    for a dry run (which never opened an index at all)."""
    if index is None:
        return None
    _, summary = embed_progress(index.status().embeds)
    await index.close()
    return (
        f"{summary} (the hub's own background worker for this vault will "
        f"finish draining the backlog the next time it opens this index)."
    )


async def _run_v2_import(
    source_path: str, vault_root: str, vault_name: str, *, dry_run: bool
) -> tuple[ImportReport, str | None]:
    engine, index = await _open_engine_and_index(vault_root, vault_name, dry_run=dry_run)
    store_root = v2_source.find_store_root(Path(source_path))
    entries = v2_source.iter_source_entries(store_root)
    mapped = (v2_source.map_v2_entry(entry) for entry in entries)
    runner = ImportRunner(engine)
    report = await runner.run("v2", str(store_root), mapped, dry_run=dry_run)
    return report, await _index_status_line(index)


async def _run_bm_import(
    source_path: str, vault_root: str, vault_name: str, *, dry_run: bool
) -> tuple[ImportReport, str | None]:
    engine, index = await _open_engine_and_index(vault_root, vault_name, dry_run=dry_run)
    vault_path = Path(source_path)
    entries = bm_source.iter_source_entries(vault_path)
    mapped = (bm_source.map_bm_entry(entry) for entry in entries)
    runner = ImportRunner(engine)
    report = await runner.run("basic-memory", str(vault_path), mapped, dry_run=dry_run)
    return report, await _index_status_line(index)


def _print_report(report: ImportReport, index_status_line: str | None, *, as_json: bool) -> None:
    if as_json:
        payload = report.to_json()
        if index_status_line is not None:
            payload["index_status"] = index_status_line
        print(json.dumps(payload, indent=2))
    else:
        print(report.summary())
        if index_status_line is not None:
            print(index_status_line)


def _import_v2(args: argparse.Namespace) -> None:
    report, index_status_line = asyncio.run(
        _run_v2_import(args.path, args.vault, args.vault_name, dry_run=args.dry_run)
    )
    _print_report(report, index_status_line, as_json=args.json)


def _import_basic_memory(args: argparse.Namespace) -> None:
    report, index_status_line = asyncio.run(
        _run_bm_import(args.path, args.vault, args.vault_name, dry_run=args.dry_run)
    )
    _print_report(report, index_status_line, as_json=args.json)


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
    elif args.command == "oauth":
        if args.oauth_command == "set-password":
            _oauth_set_password(args.username)
        elif args.oauth_command == "machine-client":
            _oauth_machine_client(args.name, args.profile, args.scopes)
        elif args.oauth_command == "clients":
            _oauth_clients()
        elif args.oauth_command == "gc":
            _oauth_gc()
    elif args.command == "import":
        if args.import_source == "v2":
            _import_v2(args)
        elif args.import_source == "basic-memory":
            _import_basic_memory(args)


if __name__ == "__main__":
    main()
