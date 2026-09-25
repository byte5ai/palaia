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

And the other half of the contract: a hub with no ``telegram:`` section
runs an *inert* connector (issue #463 builds one on every hub, so the
dashboard can add the first bot live) — no task, every webhook key a 404,
and tools that list no chat and can send nowhere. Then the editor itself,
end to end: a bot, a rule and a grant added through ``/api/telegram`` on
that hub reach ``config.yaml`` (and read back through ``load_config``),
start a poll task and let the profile send — with no restart.
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


def _write_sectionless_config(home: Path) -> None:
    # The profile flag without the section: the tools mount over the empty
    # connector, and default-deny means they can do nothing.
    (home / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "# the operator's own comment, which an edit must not lose\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      telegram: true\n",
        encoding="utf-8",
    )


async def test_a_hub_without_a_telegram_section_runs_an_inert_connector(
    tmp_path: Path,
) -> None:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    _write_sectionless_config(tmp_path)
    config = load_config(home=tmp_path, create_if_missing=False)
    assert config.telegram is None
    api = FakeBotApi(park_when_empty=True)
    production = await build_production_app(config, home=tmp_path, telegram_api=api)
    assert production.telegram is not None
    assert production.telegram.service.settings.bots == []
    try:
        async with production.app.router.lifespan_context(production.app):
            poll_tasks = [
                t for t in asyncio.all_tasks() if t.get_name().startswith(POLL_TASK_PREFIX)
            ]
            assert poll_tasks == []
            async with _http(production) as http:
                response = await http.post("/telegram/webhook/x", json={"update_id": 1})
                status = await http.get("/api/telegram/status")
            assert response.status_code == 404
            assert status.status_code == 200, status.text
            assert status.json()["bots"] == [] and status.json()["editable"] is True

            url = f"{BASE_URL}/mcp/default/"
            async with Client(mcp_client_transport(production.app, url)) as client:
                listed = await client.call_tool("telegram_list_chats", {})
                sent = await client.call_tool(
                    "telegram_send",
                    {"bot": "any", "chat": "-1001", "text": "hello"},
                    raise_on_error=False,
                )
            assert listed.structured_content == {"chats": []}
            assert sent.is_error
    finally:
        await _close(production)
    # Nothing reached Telegram, and nothing was written.
    assert api.get_updates_calls == [] and api.sent == []
    assert "\ntelegram:" not in (tmp_path / "config.yaml").read_text(encoding="utf-8")


async def test_the_first_bot_is_added_from_the_dashboard_without_a_restart(
    tmp_path: Path,
) -> None:
    """Issue #463's whole point, through the production assembly: a hub
    with no ``telegram:`` section gets a bot, its token, a rule and a grant
    from ``/api/telegram`` — and polls, routes and sends right away."""
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    _write_sectionless_config(tmp_path)
    api = FakeBotApi(
        [[message_update(10, chat_id=-1002, text="captured live", message_id=1)]],
        park_when_empty=True,
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path, telegram_api=api)
    runtime = production.telegram
    assert runtime is not None
    events: list[Envelope] = []
    production.event_bus.on(events.append)
    try:
        async with production.app.router.lifespan_context(production.app):
            assert runtime.tasks == {}
            async with _http(production) as http:
                created = await http.post(
                    "/api/telegram/bots", json={"key": "support", "label": "Support"}
                )
                assert created.status_code == 200, created.text
                bot = created.json()["bots"][0]
                assert bot["token_secret"] == "telegram_support"
                assert bot["token_stored"] is False
                # The token goes into the secret store, by name — the
                # write-only surface every credential already uses.
                stored = await http.put(
                    f"/api/secrets/{bot['token_secret']}", json={"value": BOT_A_TOKEN}
                )
                assert stored.status_code == 200, stored.text
                routed = await http.post(
                    "/api/telegram/routes",
                    json={
                        "bot": "support",
                        "chat": "-1002",
                        "destination": {"kind": "inbox", "vault": "work"},
                    },
                )
                assert routed.status_code == 200, routed.text
                granted = await http.put(
                    "/api/telegram/grants/default", json={"bots": ["support"], "chats": ["*"]}
                )
                assert granted.status_code == 200, granted.text
                status = (await http.get("/api/telegram/status")).json()
            assert _only(status["bots"])["token_stored"] is True

            # Polling started live, with the token stored from the screen,
            # and the rule delivered the first message into the vault.
            assert set(runtime.tasks) == {"support"}
            await _until(lambda: bool(_inbox_files(tmp_path)))
            assert "captured live" in _inbox_files(tmp_path)[0].read_text()
            assert {call["token"] for call in api.get_updates_calls} == {BOT_A_TOKEN}

            # The grant applies to the already-mounted profile's tools.
            url = f"{BASE_URL}/mcp/default/"
            async with Client(mcp_client_transport(production.app, url)) as client:
                sent = await client.call_tool(
                    "telegram_send", {"bot": "support", "chat": "-1002", "text": "on it"}
                )
            assert not sent.is_error
            assert api.sent[-1]["token"] == BOT_A_TOKEN

            updated = [e for e in events if e.event == "telegram.config.updated"]
            assert [(e.data["subject"], e.data["action"]) for e in updated] == [
                ("bot", "created"),
                ("route", "created"),
                ("grant", "created"),
            ]
            assert {e.origin for e in updated} == {"telegram"}
    finally:
        await _close(production)

    # Written back to config.yaml — the operator's comment kept — and read
    # back by the loader exactly as saved: the next start is this one.
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "# the operator's own comment" in text
    assert BOT_A_TOKEN not in text
    reloaded = load_config(home=tmp_path, create_if_missing=False)
    assert reloaded.telegram is not None
    assert reloaded.telegram == runtime.service.settings
    assert [p.path for p in (reloaded.gateway.profiles if reloaded.gateway else [])] == ["default"]


def _only(items: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(items) == 1, items
    return items[0]


# ------------------------------------------------------ tokens and scopes


async def test_a_dashboard_token_for_a_telegram_profile_can_use_the_tools(
    tmp_path: Path,
) -> None:
    """With auth on (the shipped default), the token the dashboard mints for
    a ``telegram: true`` profile — empty ``scopes``, so the profile's
    default — carries ``telegram:read``/``telegram:send`` and reaches the
    tools; a vault-only token for the same profile is refused by scope."""
    await _prepare_home(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "auth_enabled: false\n", "auth_enabled: true\n"
        ),
        encoding="utf-8",
    )
    api = FakeBotApi(park_when_empty=True)
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path, telegram_api=api)
    _store_secrets(production)
    try:
        async with production.app.router.lifespan_context(production.app):
            async with _http(production) as http:
                minted = await http.post(
                    "/api/auth/tokens", json={"name": "phone", "profile": "default"}
                )
            assert minted.status_code == 200, minted.text
            assert {"telegram:read", "telegram:send"} <= set(minted.json()["info"]["scopes"])
            vault_only = production.token_store.create("ro", "default", ["vault:work:read"])

            url = f"{BASE_URL}/mcp/default/"
            async with Client(
                mcp_client_transport(production.app, url, token=minted.json()["token"])
            ) as client:
                listed = await client.call_tool("telegram_list_chats", {})
            async with Client(
                mcp_client_transport(production.app, url, token=vault_only.token)
            ) as client:
                refused = await client.call_tool(
                    "telegram_list_chats", {}, raise_on_error=False
                )
    finally:
        await _close(production)
    assert not listed.is_error
    assert refused.is_error
    text = refused.content[0].text if refused.content else ""  # type: ignore[union-attr]
    assert "telegram:read" in text
