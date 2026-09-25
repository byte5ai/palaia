"""The dashboard's Telegram editor (issue #463): bots, routing rules and
grants edited through ``/api/telegram``, written back to ``config.yaml``
and applied to the running connector.

Unit-level: the router on a bare app over a real
:class:`~palaia_hub.telegram.runtime.TelegramRuntime` and the fakes in
``conftest.py``, with a real ``config.yaml`` in a temp dir. The production
assembly — an editor on a hub that had no ``telegram:`` section, the token
stored through ``/api/secrets``, the tools sending under the new grant — is
``test_serve_wiring.py``'s; that every route is behind the admin session is
the route walk's (``tests/test_admin_session.py``).

What matters beyond the happy paths:

* **An edit is validated as ``config.yaml`` is** — a rule naming an unknown
  bot, a webhook bot without its secret, a malformed chat: refused, and
  neither the file nor the running connector changes.
* **Every saved edit round-trips** through :func:`palaia_hub.config.
  load_config`, and the rest of the file — comments included — is kept.
* **No token travels here.** A bot body carrying one is refused; the
  status never carries one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi import FastAPI

from palaia_hub.config import load_config
from palaia_hub.curator.profile import CURATOR_PROFILE_PATH
from palaia_hub.telegram.dashboard_api import (
    EVENT_CONFIG_UPDATED,
    build_telegram_dashboard_router,
    render_telegram_section,
)
from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.runtime import TelegramRuntime
from palaia_hub.telegram.service import TelegramService

from .conftest import (
    BOT_A_TOKEN,
    TWO_BOT_SETTINGS,
    FakeBotApi,
    FakeSecrets,
    FakeVault,
    RecordingBus,
    message_update,
)

pytestmark = pytest.mark.anyio

CONFIG_HEAD = "mode: locked\nauth_enabled: false\n# keep this comment\n"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    settings = TelegramSettings.model_validate(TWO_BOT_SETTINGS)
    path.write_text(
        CONFIG_HEAD + "telegram:\n" + render_telegram_section(settings) + "port: 8787\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def runtime(service: TelegramService, api: FakeBotApi) -> TelegramRuntime:
    return TelegramRuntime(service, api)


@pytest.fixture
def events() -> RecordingBus:
    return RecordingBus()


@pytest.fixture
def app(
    runtime: TelegramRuntime, secrets: FakeSecrets, config_path: Path, events: RecordingBus
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_telegram_dashboard_router(
            runtime, secrets, config_path=config_path, publish=events
        )
    )
    return app


async def _call(
    app: FastAPI, method: str, path: str, body: Any = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hub") as client:
        return await client.request(method, path, json=body)


async def _ok(app: FastAPI, method: str, path: str, body: Any = None) -> dict[str, Any]:
    response = await _call(app, method, path, body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _saved(config_path: Path) -> TelegramSettings:
    """What the next start would run: config.yaml through the real loader."""
    config = load_config(home=config_path.parent, create_if_missing=False)
    assert config.telegram is not None
    return config.telegram


def _bot(status: dict[str, Any], key: str) -> dict[str, Any]:
    return next(bot for bot in status["bots"] if bot["key"] == key)


# -------------------------------------------------------------------- bots


async def test_a_bot_is_added_saved_and_applied(
    app: FastAPI,
    config_path: Path,
    runtime: TelegramRuntime,
    service: TelegramService,
    events: RecordingBus,
) -> None:
    status = await _ok(
        app, "POST", "/api/telegram/bots", {"key": "alerts", "label": "Alerts bot"}
    )
    alerts = _bot(status, "alerts")
    assert alerts["label"] == "Alerts bot"
    assert alerts["token_secret"] == "telegram_alerts"
    assert alerts["token_stored"] is False
    # Live: the connector knows it, and it has a poller.
    assert service.settings.bot("alerts") is not None
    assert "alerts" in runtime.pollers
    # Saved: the next start runs the same section, and nothing else in the
    # file moved.
    assert _saved(config_path) == service.settings
    text = config_path.read_text(encoding="utf-8")
    assert text.startswith(CONFIG_HEAD) and text.endswith("port: 8787\n")
    assert events.named(EVENT_CONFIG_UPDATED) == [
        {"subject": "bot", "action": "created", "key": "alerts"}
    ]


async def test_a_webhook_bot_gets_its_echo_secret_named(app: FastAPI) -> None:
    status = await _ok(
        app, "POST", "/api/telegram/bots", {"key": "hooked", "transport": "webhook"}
    )
    hooked = _bot(status, "hooked")
    assert hooked["webhook_secret"] == "telegram_hooked_webhook"
    assert hooked["webhook_secret_stored"] is False
    assert hooked["polling"] is None


async def test_a_duplicate_or_malformed_bot_is_refused(
    app: FastAPI, config_path: Path
) -> None:
    before = config_path.read_text(encoding="utf-8")
    duplicate = await _call(app, "POST", "/api/telegram/bots", {"key": "support"})
    assert duplicate.status_code == 409
    malformed = await _call(app, "POST", "/api/telegram/bots", {"key": "Not A Key"})
    assert malformed.status_code == 400
    assert "lowercase" in malformed.json()["detail"]
    assert config_path.read_text(encoding="utf-8") == before


async def test_a_secret_name_the_store_would_refuse_is_refused(app: FastAPI) -> None:
    response = await _call(
        app, "POST", "/api/telegram/bots", {"key": "alerts", "token_secret": "no spaces"}
    )
    assert response.status_code == 400
    assert "secret name" in response.json()["detail"]


async def test_a_bot_body_carrying_a_token_is_refused(
    app: FastAPI, config_path: Path
) -> None:
    """The token belongs in the secret store. A client that sends one along
    with the bot is told so — the field is not silently dropped, and it is
    certainly not written to config.yaml."""
    response = await _call(
        app, "POST", "/api/telegram/bots", {"key": "leaky", "token": BOT_A_TOKEN}
    )
    assert response.status_code == 422
    assert BOT_A_TOKEN not in config_path.read_text(encoding="utf-8")
    patched = await _call(app, "PATCH", "/api/telegram/bots/support", {"token": BOT_A_TOKEN})
    assert patched.status_code == 422


async def test_a_bot_is_edited_in_place(
    app: FastAPI, config_path: Path, runtime: TelegramRuntime
) -> None:
    status = await _ok(
        app, "PATCH", "/api/telegram/bots/personal", {"label": "Me", "enabled": False}
    )
    personal = _bot(status, "personal")
    assert personal["label"] == "Me" and personal["enabled"] is False
    assert "personal" not in runtime.pollers
    # An explicit null clears the label; the key shows again.
    status = await _ok(app, "PATCH", "/api/telegram/bots/personal", {"label": None})
    assert _bot(status, "personal")["label"] == "personal"
    assert _bot(status, "personal")["configured_label"] is None
    assert _saved(config_path).bot("personal").label is None  # type: ignore[union-attr]


async def test_switching_transport_names_or_drops_the_echo_secret(app: FastAPI) -> None:
    status = await _ok(app, "PATCH", "/api/telegram/bots/support", {"transport": "webhook"})
    assert _bot(status, "support")["webhook_secret"] == "telegram_support_webhook"
    status = await _ok(app, "PATCH", "/api/telegram/bots/support", {"transport": "polling"})
    assert _bot(status, "support")["webhook_secret"] is None
    assert _bot(status, "support")["webhook_secret_stored"] is None


async def test_an_unknown_bot_is_a_404(app: FastAPI) -> None:
    assert (await _call(app, "PATCH", "/api/telegram/bots/nobody", {})).status_code == 404
    assert (await _call(app, "DELETE", "/api/telegram/bots/nobody")).status_code == 404


async def test_a_bot_still_in_use_cannot_be_deleted(app: FastAPI, config_path: Path) -> None:
    """Removing a bot's rules is a decision about where messages go — the
    operator's, not a cascade's."""
    await _ok(app, "PUT", "/api/telegram/grants/desk", {"bots": ["personal"], "chats": ["*"]})
    refused = await _call(app, "DELETE", "/api/telegram/bots/personal")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "personal/-1002" in detail and "desk" in detail

    await _ok(app, "DELETE", "/api/telegram/routes/personal/-1002")
    await _ok(app, "DELETE", "/api/telegram/grants/desk")
    status = await _ok(app, "DELETE", "/api/telegram/bots/personal")
    assert [bot["key"] for bot in status["bots"]] == ["support"]
    assert _saved(config_path).bot("personal") is None


# ------------------------------------------------------------------ routes


async def test_a_rule_is_added_and_routes_the_next_message(
    app: FastAPI, service: TelegramService, vault: FakeVault, config_path: Path
) -> None:
    """The loop the issue asks to close: a message nothing matched, then a
    rule for one of its candidate chat keys, then the next one lands."""
    dropped = await service.handle_update(
        "support", message_update(1, chat_id=-1003, message_id=11, text="first")
    )
    assert dropped.routed is False
    status = await _ok(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "support", "chat": "-1003", "destination": {"kind": "inbox", "vault": "work"}},
    )
    assert {"bot": "support", "chat": "-1003"} in [
        {"bot": r["bot"], "chat": r["chat"]} for r in status["routes"]
    ]
    delivered = await service.handle_update(
        "support", message_update(2, chat_id=-1003, message_id=12, text="second")
    )
    assert delivered.routed is True and delivered.delivered is True
    assert len(vault.captures) == 1
    assert ("support", "-1003") in {(r.bot, r.chat) for r in _saved(config_path).routes}


async def test_a_rule_naming_an_unknown_bot_is_refused(
    app: FastAPI, config_path: Path, service: TelegramService
) -> None:
    """``HubConfig``'s own cross-reference check, applied to the edit."""
    before = config_path.read_text(encoding="utf-8")
    response = await _call(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "ghost", "chat": "*", "destination": {"kind": "event"}},
    )
    assert response.status_code == 400
    assert "ghost" in response.json()["detail"]
    assert config_path.read_text(encoding="utf-8") == before
    assert all(r.bot != "ghost" for r in service.routes.routes)


async def test_a_rule_is_validated_like_config_yaml(app: FastAPI) -> None:
    no_vault = await _call(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "support", "chat": "*", "destination": {"kind": "inbox"}},
    )
    assert no_vault.status_code == 422
    bad_chat = await _call(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "support", "chat": "not a chat", "destination": {"kind": "event"}},
    )
    assert bad_chat.status_code == 422
    duplicate = await _call(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "support", "chat": "-1001", "destination": {"kind": "event"}},
    )
    assert duplicate.status_code == 409


async def test_a_rule_is_replaced_and_may_move(app: FastAPI, config_path: Path) -> None:
    status = await _ok(
        app,
        "PUT",
        "/api/telegram/routes/support/-1001",
        {"bot": "support", "chat": "@OpsRoom", "destination": {"kind": "event", "label": "ops"}},
    )
    moved = next(r for r in status["routes"] if r["chat"] == "@opsroom")
    assert moved["target"]["label"] == "ops"
    assert all(r["chat"] != "-1001" for r in status["routes"])
    # Addressed by its normalised key — whatever case the operator typed.
    await _ok(app, "DELETE", "/api/telegram/routes/support/@OPSROOM")
    assert all(r.chat != "@opsroom" for r in _saved(config_path).routes)


async def test_replacing_onto_another_rule_is_refused(app: FastAPI) -> None:
    response = await _call(
        app,
        "PUT",
        "/api/telegram/routes/support/-1001",
        {"bot": "personal", "chat": "-1002", "destination": {"kind": "event"}},
    )
    assert response.status_code == 409


async def test_an_unknown_rule_is_a_404(app: FastAPI) -> None:
    response = await _call(app, "DELETE", "/api/telegram/routes/support/-999")
    assert response.status_code == 404


# ------------------------------------------------------------------ grants


async def test_a_grant_opens_and_closes_the_outbound_fence(
    app: FastAPI, service: TelegramService, config_path: Path
) -> None:
    from palaia_hub.telegram.models import NotPermittedError

    with pytest.raises(NotPermittedError):
        await service.send(profile="desk", bot="support", chat="-1001", text="hi")
    status = await _ok(
        app, "PUT", "/api/telegram/grants/desk", {"bots": ["support"], "chats": ["-1001"]}
    )
    assert {"profile": "desk", "bots": ["support"], "chats": ["-1001"]} in status["grants"]
    await service.send(profile="desk", bot="support", chat="-1001", text="hi")
    with pytest.raises(NotPermittedError):
        await service.send(profile="desk", bot="support", chat="-1002", text="hi")

    await _ok(app, "DELETE", "/api/telegram/grants/desk")
    with pytest.raises(NotPermittedError):
        await service.send(profile="desk", bot="support", chat="-1001", text="hi")
    assert _saved(config_path).grant("desk") is None


async def test_a_grant_is_replaced_whole(app: FastAPI) -> None:
    status = await _ok(app, "PUT", "/api/telegram/grants/default", {"bots": [], "chats": ["*"]})
    grant = next(g for g in status["grants"] if g["profile"] == "default")
    assert grant["bots"] == []


async def test_a_grant_for_the_curator_is_refused(app: FastAPI, config_path: Path) -> None:
    before = config_path.read_text(encoding="utf-8")
    response = await _call(app, "PUT", f"/api/telegram/grants/{CURATOR_PROFILE_PATH}", {})
    assert response.status_code == 400
    assert "curator" in response.json()["detail"]
    assert config_path.read_text(encoding="utf-8") == before


async def test_a_grant_naming_an_unknown_bot_is_refused(app: FastAPI) -> None:
    response = await _call(
        app, "PUT", "/api/telegram/grants/desk", {"bots": ["ghost"], "chats": ["*"]}
    )
    assert response.status_code == 400
    assert "ghost" in response.json()["detail"]


async def test_an_unknown_grant_is_a_404(app: FastAPI) -> None:
    assert (await _call(app, "DELETE", "/api/telegram/grants/nobody")).status_code == 404


# ---------------------------------------------------------- the whole file


async def test_a_hub_without_a_section_gets_one_on_the_first_edit(
    tmp_path: Path, api: FakeBotApi, secrets: FakeSecrets
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_HEAD, encoding="utf-8")
    runtime = TelegramRuntime(TelegramService(TelegramSettings(), api, secrets), api)
    app = FastAPI()
    app.include_router(build_telegram_dashboard_router(runtime, secrets, config_path=path))

    await _ok(app, "POST", "/api/telegram/bots", {"key": "support"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith(CONFIG_HEAD) and "\ntelegram:\n" in text
    assert _saved(path) == runtime.service.settings


async def test_a_save_carries_the_configuration_check(
    tmp_path: Path, api: FakeBotApi, secrets: FakeSecrets
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_HEAD, encoding="utf-8")
    service = TelegramService(
        TelegramSettings.model_validate(
            {"bots": [{"key": "support", "token_secret": "telegram_support"}]}
        ),
        api,
        secrets,
        vaults={"work": FakeVault()},
    )
    app = FastAPI()
    app.include_router(
        build_telegram_dashboard_router(TelegramRuntime(service, api), secrets, config_path=path)
    )
    status = await _ok(
        app,
        "POST",
        "/api/telegram/routes",
        {"bot": "support", "destination": {"kind": "inbox", "vault": "later"}},
    )
    assert len(status["warnings"]) == 1 and "'later'" in status["warnings"][0]
    assert status["vaults"] == ["work"]
    # The saved rule is kept all the same — structurally valid, and right
    # once that vault exists.
    assert _saved(path).routes[0].destination.vault == "later"


async def test_without_a_config_path_the_panel_is_read_only(
    runtime: TelegramRuntime, secrets: FakeSecrets
) -> None:
    app = FastAPI()
    app.include_router(build_telegram_dashboard_router(runtime, secrets))
    status = await _ok(app, "GET", "/api/telegram/status")
    assert status["editable"] is False
    response = await _call(app, "POST", "/api/telegram/bots", {"key": "alerts"})
    assert response.status_code in (404, 405)


async def test_render_leaves_the_defaults_out_but_always_says_who() -> None:
    settings = TelegramSettings.model_validate(
        {
            **TWO_BOT_SETTINGS,
            "routes": [
                *TWO_BOT_SETTINGS["routes"],
                {"bot": "support", "destination": {"kind": "event"}},
            ],
            "grants": [{"profile": "default"}],
        }
    )
    body = render_telegram_section(settings)
    assert "enabled:" not in body and "urgency:" not in body and "transport:" not in body
    assert body.startswith("  bots:\n")
    # A catch-all rule and an open grant say so, rather than by omission.
    assert "  - bot: support\n    chat: '*'\n" in body
    assert "bots:\n    - '*'\n    chats:\n    - '*'\n" in body
    assert TelegramSettings.model_validate(yaml.safe_load("telegram:\n" + body)["telegram"]) == (
        settings
    )
    assert render_telegram_section(TelegramSettings()) == "  bots: []\n"
