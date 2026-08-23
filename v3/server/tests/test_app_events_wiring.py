"""SPEC-201's central claim, proven at the ``create_app()`` level: one bus,
several producers (vault registry, token store, the app's own lifespan),
several consumers (in-process, and — through the exact same publish call —
webhooks). No subprocess needed here (unlike ``test_events.py``'s SSE
tests): everything below only touches the in-process
:class:`~palaia_hub.events.EventBus`, which ``TestClient``'s lifespan
context makes available synchronously.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from palaia_hub.app import create_app
from palaia_hub.auth import TokenStore
from palaia_hub.config import HubConfig
from palaia_hub.events.schema import Envelope
from palaia_hub.hooks import HookOutbox, HookStore
from palaia_hub.vault import EventBus as VaultEventBus
from palaia_hub.vault import VaultRegistry


def test_hub_started_fires_during_app_startup() -> None:
    app = create_app(HubConfig())
    received: list[Envelope] = []
    app.state.event_bus.on(received.append)

    with TestClient(app):
        pass

    assert any(e.event == "hub.started" for e in received)


def test_a_vault_write_reaches_the_bus_as_memory_entry_created(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "home", bus=VaultEventBus())
    app = create_app(HubConfig(), vault_registry=registry)
    received: list[Envelope] = []
    app.state.event_bus.on(received.append)

    async def _create() -> None:
        engine = await registry.create("work", tmp_path / "vault")
        await engine.write_note("a.md", body="hello", title="A")

    with TestClient(app):
        asyncio.run(_create())

    created = [e for e in received if e.event == "memory.entry.created"]
    assert any(e.vault == "work" and e.data.get("path") == "a.md" for e in created)


def test_a_verified_token_reaches_the_bus_as_client_connected(tmp_path: Path) -> None:
    token_store = TokenStore(home=tmp_path)
    created = token_store.create("codex", "default", [])
    app = create_app(HubConfig(), token_store=token_store)
    received: list[Envelope] = []
    app.state.event_bus.on(received.append)

    with TestClient(app):
        token_store.verify(created.token)
        token_store.verify(created.token)  # second call: no second event

    connected = [e for e in received if e.event == "client.connected"]
    assert len(connected) == 1
    assert connected[0].data["token_id"] == created.info.id
    assert connected[0].data["client_name"] == "codex"


def test_a_matching_hook_is_enqueued_for_a_real_vault_write(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "home", bus=VaultEventBus())
    hook_store = HookStore(tmp_path / "hooks")
    hook_outbox = HookOutbox(tmp_path / "hooks" / "outbox.sqlite3")
    hook_store.create("https://example.com/hook", ["memory.entry.created"])
    app = create_app(
        HubConfig(),
        vault_registry=registry,
        hook_store=hook_store,
        hook_outbox=hook_outbox,
    )

    async def _create() -> None:
        engine = await registry.create("work", tmp_path / "vault")
        await engine.write_note("a.md", body="hello", title="A")

    with TestClient(app):
        asyncio.run(_create())

    assert hook_outbox.count_pending() >= 1
