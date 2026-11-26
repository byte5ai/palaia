"""A write that comes through the gateway is committed as the AI app whose
access key the request carried, and its change event names that app.

Before, every such write was the engine's own ("palaia"): a note's history
and the dashboard's activity feed could not say which app saved it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client

from palaia_hub.app import create_app
from palaia_hub.auth import attribution as attribution_module
from palaia_hub.auth.attribution import client_attribution
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.wiring import build_profile_verifiers
from palaia_hub.config import HubConfig
from palaia_hub.events.bridge import to_envelope_args
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import Attribution, ChangeEvent, EventBus, VaultEngine

from ._asgi_mcp_client import mcp_client_transport

pytestmark = pytest.mark.anyio


async def _engine(tmp_path: Path, bus: EventBus | None = None) -> VaultEngine:
    engine = VaultEngine(tmp_path / "work", "work", bus=bus)
    await engine.open(purpose="Work.")
    return engine


async def test_a_tool_call_is_committed_as_the_app_its_access_key_names(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path / "home")
    created = store.create("Claude Code CLI", "default", ["vault:work:read", "vault:work:write"])
    events: list[ChangeEvent] = []
    bus = EventBus()

    async def collect(event: ChangeEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    engine = await _engine(tmp_path, bus)
    gateway = build_gateway(
        GatewayConfig(
            vaults=[VaultMountConfig(key="work", name="work", purpose="Work.")],
            profiles=[ProfileConfig(path="default", vaults=["work"])],
        ),
        {"work": EngineVaultService(engine, attribution=client_attribution(store))},
        token_verifiers=build_profile_verifiers(["default"], store),
    )
    app = create_app(HubConfig(mode="cloud", host="127.0.0.1"), gateway=gateway)

    async with app.router.lifespan_context(app):
        transport = mcp_client_transport(app, "http://testserver/mcp/default/", token=created.token)
        async with Client(transport) as client:
            result = await client.call_tool_mcp(
                "work_memory_write", {"title": "Billing service", "body": "Owns invoices."}
            )
    assert result.isError is not True

    history = await engine.history("billing-service", limit=1)
    assert history[0].author_name == "Claude Code CLI"
    written = [event for event in events if getattr(event, "permalink", None) == "billing-service"]
    assert written and written[-1].actor == "Claude Code CLI"
    assert to_envelope_args(written[-1])[1]["actor"] == "Claude Code CLI"


async def test_every_kind_of_change_carries_the_caller(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    service = EngineVaultService(engine, attribution=lambda: Attribution(client="Codex"))

    note = await service.write(title="Release checklist", body="Changelog first.")
    assert (await engine.history(note.permalink, limit=1))[0].author_name == "Codex"

    await service.edit(note.permalink, append="Then the docs.")
    assert (await engine.history(note.permalink, limit=1))[0].author_name == "Codex"

    moved = await service.move(note.permalink, "conventions")
    assert (await engine.history(moved.permalink, limit=1))[0].author_name == "Codex"

    capture = await service.capture(
        what_it_concerns="Staging database", why_keep="Easy to forget", content="Rotates monthly."
    )
    assert (await engine.history(capture.permalink, limit=1))[0].author_name == "Codex"


async def test_without_a_caller_a_write_is_the_engines_own_and_names_no_actor(
    tmp_path: Path,
) -> None:
    events: list[ChangeEvent] = []
    bus = EventBus()

    async def collect(event: ChangeEvent) -> None:
        events.append(event)

    bus.subscribe(collect)
    engine = await _engine(tmp_path, bus)
    service = EngineVaultService(engine, attribution=lambda: None)

    note = await service.write(title="Plain note", body="No caller.")

    assert (await engine.history(note.permalink, limit=1))[0].author_name == "palaia"
    written = [event for event in events if getattr(event, "permalink", None) == note.permalink]
    assert written[-1].actor is None
    assert "actor" not in to_envelope_args(written[-1])[1]


def test_the_caller_is_looked_up_by_access_key_and_unknown_callers_are_not_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("LM Studio", "default", [])
    current = client_attribution(store)

    def calling_as(client_id: str | None) -> None:
        token = None if client_id is None else SimpleNamespace(client_id=client_id)
        monkeypatch.setattr(attribution_module, "get_access_token", lambda: token)

    calling_as(created.info.id)
    assert current() == Attribution(client="LM Studio")
    # Signed in with the owner's account: no access key, so no app to name.
    calling_as("oauth-client-without-a-key")
    assert current() is None
    # Not a tool call at all (the dashboard, a background job).
    calling_as(None)
    assert current() is None
    assert client_attribution(None)() is None
