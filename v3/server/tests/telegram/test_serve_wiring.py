"""Issue #439: a hub whose ``config.yaml`` has a ``telegram:`` section actually
runs the connector — through :func:`palaia_hub.serve.build_production_app`,
the exact assembly ``palaia-hub serve`` runs, with only the Bot API faked.

Modelled on ``tests/test_serve_messenger_spec403.py``: the real lifespan,
real MCP clients over ``mcp_client_transport``, the real secret store, the
real messenger and vault. What is asserted is the wiring, end to end:

* the polling bot's task is running and polls with that bot's token; a
  scripted update routed to the messenger lands as a real envelope, one
  routed to an inbox lands as a real capture, and the events reach the real
  bus with origin ``telegram``;
* ``POST /telegram/webhook/<bot>`` is mounted, and refuses a delivery
  without the secret header;
* a ``telegram: true`` profile carries the five tools — and still does after
  every kind of runtime profile rebuild — while a profile without the flag
  does not;
* shutdown leaves no poll task pending, and closes the Bot API client only
  when the hub created it.

And the other half of the contract: a hub with no ``telegram:`` section is
unchanged — no route, no task, no tool.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.events.schema import Envelope
from palaia_hub.gateway.telegram_tools import TELEGRAM_TOOL_ACTIONS
from palaia_hub.serve import DIRECTORY_FILENAME, ProductionApp, build_production_app
from palaia_hub.telegram.runtime import POLL_TASK_PREFIX
from palaia_hub.telegram.webhook import SECRET_HEADER
from palaia_hub.vault import VaultRegistry

from .conftest import BOT_A_TOKEN, BOT_B_TOKEN, FakeBotApi, message_update

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "auth"))
from _asgi_mcp_client import mcp_client_transport  # noqa: E402

pytestmark = pytest.mark.anyio

BASE_URL = "https://testserver"
HOOK_SECRET = "a-random-webhook-secret-value"  # noqa: S105 - test fixture
TELEGRAM_TOOLS = set(TELEGRAM_TOOL_ACTIONS)


async def _prepare_home(home: Path) -> str:
    """One vault, one live directory session (the messenger recipient), and
    a config.yaml wiring both into a two-bot Telegram section. Returns the
    session's handle."""
    registry = VaultRegistry(home)
    await registry.create("work", home / "vaults" / "work", purpose="work vault.")
    store = DirectoryStore(home / DIRECTORY_FILENAME)
    try:
        registered = await DirectoryService(store).register(scope="ops")
    finally:
        store.close()
    handle = registered.session.handle
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      telegram: true\n"
        "    - path: plain\n"
        "      vaults: [work]\n"
        "telegram:\n"
        "  bots:\n"
        "    - key: support\n"
        "      token_secret: telegram_support\n"
        "    - key: hooked\n"
        "      token_secret: telegram_hooked\n"
        "      transport: webhook\n"
        "      webhook_secret: telegram_hooked_hook\n"
        "  routes:\n"
        "    - bot: support\n"
        '      chat: "-1001"\n'
        "      destination:\n"
        "        kind: messenger\n"
        f"        to: {handle}\n"
        "    - bot: support\n"
        '      chat: "-1002"\n'
        "      destination:\n"
        "        kind: inbox\n"
        "        vault: work\n"
        "    - bot: hooked\n"
        '      chat: "*"\n'
        "      destination:\n"
        "        kind: inbox\n"
        "        vault: work\n"
        "  grants:\n"
        "    - profile: default\n",
        encoding="utf-8",
    )
    return handle


def _store_secrets(production: ProductionApp) -> None:
    """Through the secret store the production app built — the one the
    connector reads — before the lifespan starts polling."""
    assert production.secret_store is not None
    production.secret_store.put("telegram_support", BOT_A_TOKEN)
    production.secret_store.put("telegram_hooked", BOT_B_TOKEN)
    production.secret_store.put("telegram_hooked_hook", HOOK_SECRET)


async def _close(production: ProductionApp) -> None:
    await production.dynamic_gateway.aclose()
    for attribute in ("stash_store", "directory_store", "messenger_store"):
        store = getattr(production, attribute)
        if store is not None:
            store.close()
    for index in production.indexes.values():
        await index.close()


async def _tool_names(production: ProductionApp, profile: str) -> set[str]:
    transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/{profile}/")
    async with Client(transport) as client:
        return {tool.name for tool in await client.list_tools()}


async def _until(predicate: Any, *, seconds: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


def _inbox_files(home: Path) -> list[Path]:
    return sorted((home / "vaults" / "work" / "inbox").glob("*.md"))


def _http(production: ProductionApp) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=production.app), base_url=BASE_URL
    )


# ------------------------------------------------------------ the whole path


async def test_a_telegram_section_runs_the_connector_end_to_end(tmp_path: Path) -> None:
    handle = await _prepare_home(tmp_path)
    api = FakeBotApi(
        [
            [
                message_update(10, chat_id=-1001, text="the deploy is stuck", message_id=1),
                message_update(11, chat_id=-1002, text="remember the new VPN", message_id=2),
            ]
        ],
        park_when_empty=True,
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path, telegram_api=api)
    runtime = production.telegram
    assert runtime is not None
    _store_secrets(production)
    events: list[Envelope] = []
    production.event_bus.on(events.append)
    messenger_store = production.messenger_store
    assert messenger_store is not None
    try:
        async with production.app.router.lifespan_context(production.app):
            # The polling bot's task runs, polling with *its* token; the
            # webhook bot has no poller at all.
            assert set(runtime.tasks) == {"support"}
            task = runtime.tasks["support"]
            assert task.get_name() == f"{POLL_TASK_PREFIX}support"
            await _until(lambda: api.parked_polls >= 1)
            assert not task.done()
            assert {call["token"] for call in api.get_updates_calls} == {BOT_A_TOKEN}

            # The messenger route delivered a real envelope, from the owner.
            await _until(lambda: bool(messenger_store.inbox(handle)[0]))
            items, _expired = messenger_store.inbox(handle)
            assert len(items) == 1
            envelope = items[0].envelope
            assert envelope.from_ == "owner"
            assert "the deploy is stuck" in envelope.subject
            # The inbox route captured into the real vault.
            await _until(lambda: bool(_inbox_files(tmp_path)))
            assert "remember the new VPN" in _inbox_files(tmp_path)[0].read_text()
            # And the connector's events reached the real bus, labelled.
            received = [e for e in events if e.event == "telegram.message.received"]
            assert len(received) == 2
            assert {e.origin for e in received} == {"telegram"}
            assert all("text" not in e.data for e in received)

            # The webhook route is mounted, secret-gated, and routes.
            update = message_update(20, chat_id=-1003, text="pushed, not polled", message_id=3)
            async with _http(production) as http:
                refused = await http.post("/telegram/webhook/hooked", json=update)
                wrong = await http.post(
                    "/telegram/webhook/hooked", json=update, headers={SECRET_HEADER: "nope"}
                )
                accepted = await http.post(
                    "/telegram/webhook/hooked", json=update, headers={SECRET_HEADER: HOOK_SECRET}
                )
                polling_bot = await http.post(
                    "/telegram/webhook/support", json=update, headers={SECRET_HEADER: HOOK_SECRET}
                )
            assert refused.status_code == 401
            assert wrong.status_code == 401
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["routed"] is True
            assert accepted.json()["delivered"] is True
            assert polling_bot.status_code == 404
            assert len(_inbox_files(tmp_path)) == 2

            # The tools: on the flagged profile, not on the other one.
            assert TELEGRAM_TOOLS <= await _tool_names(production, "default")
            assert not TELEGRAM_TOOLS & await _tool_names(production, "plain")
    finally:
        await _close(production)

    # Shutdown: nothing left pending, and a client the caller handed in is
    # the caller's to close.
    assert task.done()
    assert runtime.tasks == {}
    assert api.cancelled_polls == 1
    assert api.closed is False


async def test_the_tools_survive_every_runtime_profile_rebuild(tmp_path: Path) -> None:
    """The bug this issue found twice over: a profile rebuilt at runtime —
    an external server connected, a PATCH from the profile editor, a vault
    added — came back without its Telegram tools (the service was never
    handed to the rebuild) or without its flag (the edit reset it)."""
    await _prepare_home(tmp_path)
    api = FakeBotApi(park_when_empty=True)
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path, telegram_api=api)
    _store_secrets(production)
    try:
        async with production.app.router.lifespan_context(production.app):
            assert TELEGRAM_TOOLS <= await _tool_names(production, "default")

            await production.dynamic_gateway.set_profile_upstreams("default", [])
            assert TELEGRAM_TOOLS <= await _tool_names(production, "default")

            async with _http(production) as http:
                patched = await http.patch("/api/gateway/profiles/default", json={"label": "Desk"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["telegram"] is True
            assert TELEGRAM_TOOLS <= await _tool_names(production, "default")

            async with _http(production) as http:
                created = await http.post(
                    "/api/vaults", json={"key": "notes", "purpose": "More notes."}
                )
            assert created.status_code in (200, 201), created.text
            profile = next(
                p for p in production.dynamic_gateway.config.profiles if p.path == "default"
            )
            assert "notes" in profile.vaults
            assert TELEGRAM_TOOLS <= await _tool_names(production, "default")
    finally:
        await _close(production)


async def test_the_hub_closes_a_bot_api_client_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``telegram_api`` passed, the hub builds its own client — and,
    owning it, releases it at shutdown."""
    await _prepare_home(tmp_path)
    created: list[FakeBotApi] = []

    def _build_client() -> FakeBotApi:
        client = FakeBotApi(park_when_empty=True)
        created.append(client)
        return client

    monkeypatch.setattr("palaia_hub.serve.HttpBotApi", _build_client)
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    _store_secrets(production)
    try:
        async with production.app.router.lifespan_context(production.app):
            assert len(created) == 1
            await _until(lambda: created[0].parked_polls >= 1)
            assert created[0].closed is False
    finally:
        await _close(production)
    assert created[0].closed is True


# ------------------------------------------------------ no telegram section


async def test_a_hub_without_a_telegram_section_is_unchanged(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    # The profile flag without the section: the tools need a service to
    # exist, and there is none — the "flag ahead of the service" contract.
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      telegram: true\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.telegram is None
    production = await build_production_app(config, home=tmp_path)
    assert production.telegram is None
    try:
        async with production.app.router.lifespan_context(production.app):
            poll_tasks = [
                t for t in asyncio.all_tasks() if t.get_name().startswith(POLL_TASK_PREFIX)
            ]
            assert poll_tasks == []
            async with _http(production) as http:
                response = await http.post("/telegram/webhook/x", json={"update_id": 1})
            assert response.status_code == 404
            assert not TELEGRAM_TOOLS & await _tool_names(production, "default")
    finally:
        await _close(production)
