"""Production app assembly (SPEC-210).

Before this module, ``palaia-hub serve`` never wired an MCP gateway at all
— ``cli.py``'s own prior docstring said so explicitly: the wizard's
``POST /api/vaults`` created a vault the dashboard could see, but no MCP
client could ever reach it, restart or not, because there was no gateway
mounted in the first place. That is the gap SPEC-210's "dynamic mounting"
deliverable actually closes: not just *rebuildable* profiles, but the first
*real* profile assembly a running hub uses.

:func:`build_production_app` is the one place that does this wiring, used
by both ``palaia-hub serve`` (:mod:`palaia_hub.cli`) and this SPEC's own
e2e test — so the test exercises the exact code path production runs, not
a parallel stand-in of it.

Every vault the registry already knows about gets a real
:class:`~palaia_hub.index.VaultIndex` opened (SPEC-104's background embed
worker included) and is mounted under whichever profile(s)
``config.yaml``'s ``gateway:`` section names — or the single
:data:`~palaia_hub.gateway.config.DEFAULT_GATEWAY_PROFILE` profile over
every vault, when that section is absent (SPEC-301) — on a
:class:`~palaia_hub.gateway.dynamic.DynamicGateway`. A vault created later,
through the wizard, is added to that same running gateway by
:func:`palaia_hub.dashboard_api.build_dashboard_router`'s ``create_vault``
handler — no restart, per that module's ``dynamic_gateway`` parameter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .app import create_app
from .auth import TokenStore
from .automations import AutomationOutbox, AutomationStore
from .automations.outbox import OUTBOX_RELATIVE_PATH as AUTOMATIONS_OUTBOX_RELATIVE_PATH
from .config import HubConfig, palaia_home
from .curator.wiring import STASH_FILENAME, CuratorWiring, build_curator
from .directory.service import DirectoryService
from .directory.store import DirectoryStore
from .events import EventBus, publish_from_hook
from .events.schema import HubEventHook
from .gateway import DynamicGateway, VaultService
from .gateway.config import DEFAULT_GATEWAY_PROFILE, GatewayConfig, VaultMountConfig
from .gateway.settings_bridge import (
    apply_vault_overrides,
    resolve_full_gateway_profiles,
    resolve_upstreams,
)
from .gateway.wiring import EngineVaultService
from .hooks import HookStore
from .index import VaultIndex
from .market import CuratedIndexClient, InstallService, ManualEntryStore, MarketService
from .notifications import NotificationStore
from .notifications.store import NOTIFICATIONS_RELATIVE_PATH
from .oauth import AuthorizationServer
from .oauth.verifier import build_profile_auth
from .registry import RegistryClient
from .stash.service import StashService
from .stash.store import StashStore
from .upstream.monitor import UpstreamHealthMonitor
from .upstream.secrets import SecretStore
from .upstream.service import UpstreamService
from .vault import EventBus as VaultEventBus
from .vault import VaultEngine, VaultRegistry

#: The hub's one session-directory database (SPEC-402), named after
#: ``STASH_FILENAME``'s own convention — one file per hub-level store,
#: living next to it under the hub's home directory.
DIRECTORY_FILENAME = "directory.db"


@dataclass
class ProductionApp:
    """Everything :func:`build_production_app` assembled, for the caller to
    hand to uvicorn and to close in reverse order at shutdown."""

    app: FastAPI
    registry: VaultRegistry
    dynamic_gateway: DynamicGateway
    indexes: dict[str, VaultIndex]
    event_bus: EventBus
    token_store: TokenStore
    #: The wired-up curator (SPEC-206), or ``None`` when
    #: ``curator.enabled`` is off. Its scheduler is started and stopped by
    #: the app's own lifespan; its stash handle is closed here.
    curator: CuratorWiring | None = None
    #: The hub's one stash store (SPEC-202/301), backing both the
    #: ``/mcp/stash`` tool family and, when the curator is on, its audit
    #: trail. Closed at shutdown, same as ``registry``/``indexes``.
    stash_store: StashStore | None = None
    #: The hub's one session-directory database (SPEC-402), backing the
    #: ``/mcp/directory`` tool family and the ``/api/directory`` REST
    #: mirror. Closed at shutdown, same as ``stash_store``.
    directory_store: DirectoryStore | None = None
    #: The external-server registry (SPEC-302). Its connections — including
    #: any ``stdio`` child process — are closed by the app's own lifespan;
    #: the handle is here so a caller can inspect health.
    upstream_service: UpstreamService | None = None
    #: The encrypted credential store backing those servers. Closed here,
    #: same as ``stash_store``.
    secret_store: SecretStore | None = None
    #: Marketplace install/lifecycle flows (SPEC-304). Holds no resources
    #: of its own to close — everything it touches (``upstream_service``,
    #: ``secret_store``, ``dynamic_gateway``) is already listed above.
    install_service: InstallService | None = None


def _index_event_hook(event_bus: EventBus, vault_key: str) -> HubEventHook:
    """Build a :data:`HubEventHook` promoting one vault's index events onto the bus.

    Covers SPEC-201's whole index vocabulary (``index.reindexed``,
    ``index.embed_backlog_drained``, ``doctor.finding``) — the drained event
    is what updates the dashboard's index-status tile live (SPEC-210). A
    plain function (not a lambda in the caller) so the ``vault_key``
    late-binding-in-a-loop mistake is structurally impossible.
    """

    def _hook(event: str, data: dict[str, Any]) -> None:
        publish_from_hook(event_bus, event, {"vault": vault_key, **data}, origin="index")

    return _hook


def _curator_event_hook(event_bus: EventBus) -> HubEventHook:
    """Promote the curator's ``curator.*``/``doctor.finding`` reports onto the bus."""

    def _hook(event: str, data: dict[str, Any]) -> None:
        publish_from_hook(event_bus, event, data, origin="curator")

    return _hook


def _upstream_event_hook(event_bus: EventBus) -> Callable[[str, dict[str, Any]], None]:
    """Promote ``gateway.upstream.up``/``down`` onto the public bus (SPEC-302).

    :class:`~palaia_hub.upstream.service.UpstreamService` publishes only on a
    *change* of reachability, so this is quiet for a healthy hub.
    """

    def _publish(event: str, data: dict[str, Any]) -> None:
        publish_from_hook(event_bus, event, data, origin="gateway")

    return _publish


async def build_production_app(
    config: HubConfig,
    *,
    home: Path | None = None,
    oauth_server: AuthorizationServer | None = None,
) -> ProductionApp:
    """Assemble the hub's real ``FastAPI`` app: registry, indexes, gateway.

    Args:
        config: the loaded ``HubConfig``.
        home: overrides the registry's/token store's data directory
            (``PALAIA_HOME`` otherwise) — mainly for tests that want an
            isolated, disposable hub home.
        oauth_server: the SPEC-203 authorization server, mounted when given.
            Built by the caller (``palaia_hub.cli``) because deciding whether
            one should exist — and failing loudly on a half-configured one —
            is CLI-surface behavior, not assembly.
    """
    # SPEC-201: the registry's own vault.events.EventBus is what create_app()
    # bridges onto the public event bus — every vault this registry opens
    # shares it, so a write to any vault produces exactly one public
    # memory.entry.* event, no matter which vault it hit.
    registry = VaultRegistry(home, bus=VaultEventBus())
    token_store = TokenStore(home)
    hook_store = HookStore(home)
    # SPEC-307: automations + the notification center it can write to.
    # Wired unconditionally, same posture as hook_store above — a hub
    # always has an (initially empty) automations surface once this SPEC
    # lands, no config.yaml flag gates it. Note: this hub does not wire a
    # StashService (that gap predates this SPEC — see the module docstring
    # of palaia_hub.stash.service, which stash_api/tools already fill in
    # for tests but which this production assembly has never built), so a
    # ``stash_set`` automation action fails with a plain-language error
    # rather than crashing until that gap is closed.
    automation_store = AutomationStore(home)
    automation_outbox = AutomationOutbox((home or palaia_home()) / AUTOMATIONS_OUTBOX_RELATIVE_PATH)
    notification_store = NotificationStore((home or palaia_home()) / NOTIFICATIONS_RELATIVE_PATH)
    event_bus = EventBus()

    # SPEC-303: the marketplace — official registry + curated index +
    # manual entries. Always assembled (like `hook_store` above); it costs
    # nothing until a client actually calls `/api/market/*`, unlike the
    # curator, which runs a model.
    market_kwargs: dict[str, Any] = {}
    if config.market.index_url:
        market_kwargs["index_url"] = config.market.index_url
    market_service = MarketService(
        registry_client=RegistryClient(cache_dir=home / "registry_cache" if home else None),
        curated_client=CuratedIndexClient(
            last_good_path=home / "market_curated_index.json" if home else None, **market_kwargs
        ),
        manual_store=ManualEntryStore(home / "market_manual.sqlite3" if home else None),
    )
    indexes: dict[str, VaultIndex] = {}
    vault_services: dict[str, VaultService] = {}
    mounts: list[VaultMountConfig] = []
    engines: dict[str, VaultEngine] = {}

    for record in registry.records():
        engine = await registry.get(record.name)
        index = VaultIndex(engine, on_event=_index_event_hook(event_bus, record.name))
        await index.open()
        indexes[record.name] = index
        engines[record.name] = engine
        vault_services[record.name] = EngineVaultService(engine, index)
        mounts.append(
            VaultMountConfig(
                key=record.name,
                name=record.name,
                purpose=engine.info().purpose or "A palaia memory vault.",
            )
        )

    # SPEC-301: `gateway.vaults` identity overrides, then `gateway.profiles`
    # (or the zero-config default: one `default` profile over every vault)
    # plus the curator's own profile when it runs — the *same* resolution
    # `palaia_hub.cli._maybe_oauth_server` uses to decide which resources
    # the OAuth server issues tokens for, so the two never disagree about
    # what this hub serves (deliverable #3's "one source of truth").
    mounts = apply_vault_overrides(mounts, config.gateway)
    profiles = resolve_full_gateway_profiles(
        config, [m.key for m in mounts], default_profile=DEFAULT_GATEWAY_PROFILE
    )

    # One stash for the whole hub (SPEC-202/301): backs the hub-wide
    # `/mcp/stash` mount, any profile with `stash: true`, and — when the
    # curator is on — its own audit trail, all through the one store so a
    # client's `stash_list` and the curator's audit entries never race two
    # SQLite connections on the same file.
    # `palaia_home()` (not `Path.cwd()`): the same "PALAIA_HOME env, else
    # the platform data dir" resolution every other store in this function
    # already gets from its own constructor (`VaultRegistry`, `TokenStore`,
    # `HookStore`) — `cli.py`'s `serve()` never passes `home` explicitly, so
    # falling back to the process's current directory here would put
    # `stash.db` wherever the daemon happened to be launched from.
    stash_home = Path(home) if home is not None else palaia_home()
    stash_store = StashStore(stash_home / STASH_FILENAME)
    stash_service = StashService(stash_store)

    # One session directory for the whole hub (SPEC-402): backs the
    # hub-wide `/mcp/directory` mount and any profile with `directory:
    # true`, same "one home, one file" reasoning as the stash store above.
    directory_store = DirectoryStore(stash_home / DIRECTORY_FILENAME)
    directory_service = DirectoryService(directory_store)

    # SPEC-206: the curator gets its own profile over the same vaults —
    # narrowed to seven actions and guarded by its own middleware (see
    # palaia_hub.curator.profile). Built before the gateway so the middleware
    # is attached while each profile's server is constructed, which is what
    # makes it survive a later profile rebuild.
    curator: CuratorWiring | None = None
    if config.curator.enabled and mounts:
        curator = build_curator(
            config,
            engines,
            mounts,
            home=home,
            publish=_curator_event_hook(event_bus),
            stash_service=stash_service,
            subscribe=event_bus.on,
        )

    # SPEC-302: external MCP servers. The secret store is opened
    # unconditionally (it creates its own key/db, 0600, on first use — and
    # the dashboard can store a credential before any server is connected);
    # the service starts with whatever `gateway.upstreams` names. Nothing
    # here touches the network: the first reachability probe happens in the
    # background, from the health monitor started by the app's lifespan, so
    # a hub whose upstream is down still starts instantly.
    secret_store = SecretStore(stash_home)
    upstream_service = UpstreamService(
        resolve_upstreams(config.gateway),
        secret_store=secret_store,
        publish=_upstream_event_hook(event_bus),
    )

    gateway_config = GatewayConfig(
        vaults=mounts, profiles=profiles, upstreams=resolve_upstreams(config.gateway)
    )
    # `auth_enabled` (config.py): mandatory in cloud/open (already enforced
    # at config-load time), on by default in locked mode too — see that
    # field's docstring. SPEC-301: combine it with the OAuth server's own
    # JWT verifier (when one is running) via `build_profile_auth` — a
    # profile accepts OAuth access tokens *and* SPEC-108 `plt_` tokens at
    # once, instead of only ever the latter (the gap this closes: before
    # this SPEC, a hub with `oauth.enabled: true` and `auth_enabled: false`
    # mounted its gateway with no verifier at all).
    token_verifiers = build_profile_auth(
        [p.path for p in profiles],
        key=oauth_server.key if oauth_server is not None else None,
        resources=oauth_server.resources if oauth_server is not None else None,
        token_store=token_store if config.auth_enabled else None,
    )
    dynamic_gateway = DynamicGateway(
        gateway_config,
        vault_services,
        mode=config.mode,
        token_verifiers=token_verifiers,  # type: ignore[arg-type]
        profile_middleware=curator.profile_middleware if curator else None,
        stash_service=stash_service,
        upstream_service=upstream_service,
        directory_service=directory_service,
    )
    upstream_monitor = UpstreamHealthMonitor(
        upstream_service, on_change=dynamic_gateway.refresh_upstreams
    )

    # SPEC-304: marketplace install/lifecycle flows, on top of the same
    # dynamic_gateway/upstream_service/secret_store the SPEC-302 upstream
    # surface above already built — see palaia_hub.market.install for why
    # this is a thin layer over that machinery rather than a parallel one.
    def _publish_addon_event(event: str, data: dict[str, Any]) -> None:
        publish_from_hook(event_bus, event, data, origin="market")

    install_service = InstallService(
        market_service=market_service,
        dynamic_gateway=dynamic_gateway,
        upstream_service=upstream_service,
        secret_store=secret_store,
        home=stash_home,
        config=config,
        publish=_publish_addon_event,
    )

    app = create_app(
        config,
        dynamic_gateway=dynamic_gateway,
        token_store=token_store,
        vault_services=vault_services,
        vault_registry=registry,
        indexes=indexes,
        event_bus=event_bus,
        oauth_server=oauth_server,
        stash_service=stash_service,
        directory_service=directory_service,
        hook_store=hook_store,
        market_service=market_service,
        install_service=install_service,
        curator=curator.scheduler if curator else None,
        automation_store=automation_store,
        automation_outbox=automation_outbox,
        notification_store=notification_store,
        curator_wiring=curator,
        upstream_service=upstream_service,
        upstream_monitor=upstream_monitor,
        secret_store=secret_store,
        home=home,
    )
    return ProductionApp(
        app=app,
        registry=registry,
        dynamic_gateway=dynamic_gateway,
        indexes=indexes,
        event_bus=event_bus,
        token_store=token_store,
        curator=curator,
        stash_store=stash_store,
        directory_store=directory_store,
        upstream_service=upstream_service,
        secret_store=secret_store,
        install_service=install_service,
    )


__all__ = ["ProductionApp", "build_production_app"]
