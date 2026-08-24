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
worker included) and is mounted under
:data:`~palaia_hub.dashboard_api.DEFAULT_GATEWAY_PROFILE` on a
:class:`~palaia_hub.gateway.dynamic.DynamicGateway`. A vault created later,
through the wizard, is added to that same running gateway by
:func:`palaia_hub.dashboard_api.build_dashboard_router`'s ``create_vault``
handler — no restart, per that module's ``dynamic_gateway`` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from .app import create_app
from .auth import TokenStore, build_profile_verifiers
from .config import HubConfig
from .dashboard_api import DEFAULT_GATEWAY_PROFILE
from .events import EventBus, publish_from_hook
from .events.schema import HubEventHook
from .gateway import DynamicGateway, VaultService
from .gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from .gateway.wiring import EngineVaultService
from .hooks import HookStore
from .index import VaultIndex
from .oauth import AuthorizationServer
from .vault import EventBus as VaultEventBus
from .vault import VaultRegistry


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
    event_bus = EventBus()
    indexes: dict[str, VaultIndex] = {}
    vault_services: dict[str, VaultService] = {}
    mounts: list[VaultMountConfig] = []

    for record in registry.records():
        engine = await registry.get(record.name)
        index = VaultIndex(engine, on_event=_index_event_hook(event_bus, record.name))
        await index.open()
        indexes[record.name] = index
        vault_services[record.name] = EngineVaultService(engine, index)
        mounts.append(
            VaultMountConfig(
                key=record.name,
                name=record.name,
                purpose=engine.info().purpose or "A palaia memory vault.",
            )
        )

    profiles = (
        [ProfileConfig(path=DEFAULT_GATEWAY_PROFILE, vaults=[m.key for m in mounts])]
        if mounts
        else []
    )
    gateway_config = GatewayConfig(vaults=mounts, profiles=profiles)
    # `auth_enabled` (config.py): mandatory in cloud/open (already enforced
    # at config-load time), on by default in locked mode too — see that
    # field's docstring. Building verifiers here, unconditionally on the
    # flag rather than on `mode`, matches that documented behavior exactly.
    token_verifiers = (
        build_profile_verifiers([DEFAULT_GATEWAY_PROFILE], token_store)
        if config.auth_enabled
        else {}
    )
    dynamic_gateway = DynamicGateway(
        gateway_config, vault_services, mode=config.mode, token_verifiers=token_verifiers
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
        hook_store=hook_store,
        home=home,
    )
    return ProductionApp(
        app=app,
        registry=registry,
        dynamic_gateway=dynamic_gateway,
        indexes=indexes,
        event_bus=event_bus,
        token_store=token_store,
    )


__all__ = ["ProductionApp", "build_production_app"]
