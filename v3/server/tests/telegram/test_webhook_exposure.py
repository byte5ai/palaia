"""Where the webhook route sits among the hub's other doors (issue #439).

``POST /telegram/webhook/<bot>`` is the connector's only inbound HTTP
surface, and it is deliberately **outside** ``/api/``: Telegram's servers
carry no browser session, so the admin session gate
(:mod:`palaia_hub.admin_session`) must not stand in front of it — the
secret-token header checked inside the route is its credential instead
(:mod:`palaia_hub.telegram.webhook`). These tests pin both halves on an app
where the gate is really active: the route is reachable without a session,
and it is not reachable without the secret.

And because in ``cloud``/``open`` that route is on the internet, guessing
its secret is throttled per caller the way guessing a session cookie is
(:mod:`palaia_hub.modes.rate_limit`), without ever slowing the real sender.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from palaia_hub.app import create_app
from palaia_hub.config import DashboardSettings, HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.oauth.login import SESSION_COOKIE
from palaia_hub.telegram.models import TelegramSettings
from palaia_hub.telegram.runtime import TelegramRuntime
from palaia_hub.telegram.service import TelegramService
from palaia_hub.telegram.webhook import SECRET_HEADER, WEBHOOK_PREFIX

from .conftest import BOT_A_TOKEN, FakeBotApi, FakeSecrets, FakeVault, message_update

ISSUER = "https://hub.example.test"
HOOK_SECRET = "webhook-secret-for-the-gate-test"  # noqa: S105 - test fixture
NOW = 1_800_000_000

SETTINGS: dict[str, Any] = {
    "bots": [
        {
            "key": "hooked",
            "token_secret": "telegram_hooked",
            "transport": "webhook",
            "webhook_secret": "telegram_hooked_hook",
        }
    ],
    "routes": [{"bot": "hooked", "chat": "*", "destination": {"kind": "inbox", "vault": "work"}}],
}


def _runtime(vault: FakeVault) -> TelegramRuntime:
    api = FakeBotApi()
    service = TelegramService(
        TelegramSettings.model_validate(SETTINGS),
        api,
        FakeSecrets({"telegram_hooked": BOT_A_TOKEN, "telegram_hooked_hook": HOOK_SECRET}),
        vaults={"work": vault},
    )
    return TelegramRuntime(service, api, mode="locked")


def _gated_app(home: Path, runtime: TelegramRuntime) -> tuple[FastAPI, AuthorizationServer]:
    """``locked`` + ``require_sign_in``: the admin gate, and no limiter."""
    config = HubConfig(
        mode="locked",
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer=ISSUER),
        dashboard=DashboardSettings(require_sign_in=True),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=home)
    set_owner_password(server.store, "owner", "a-long-enough-passphrase", now=NOW)
    app = create_app(config, home=home, oauth_server=server, telegram_runtime=runtime)
    return app, server


def _walk(routes: Iterable[Any]) -> Iterator[Route]:
    """Same flattening as ``tests/test_admin_session.py``'s route walk."""
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _walk(original.routes)
        elif isinstance(route, Route):
            yield route


def test_the_webhook_route_is_outside_the_admin_walk(tmp_path: Path) -> None:
    """The route walk in ``tests/test_admin_session.py`` covers ``/api/*``
    only. The webhook is not in it — correctly — so this is the test that
    says what guards it instead."""
    app, server = _gated_app(tmp_path, _runtime(FakeVault()))
    try:
        paths = {route.path for route in _walk(app.routes)}
    finally:
        server.store.close()
    assert f"{WEBHOOK_PREFIX}/{{bot}}" in paths
    assert not WEBHOOK_PREFIX.startswith("/api/")


def test_the_webhook_is_secret_gated_not_session_gated(tmp_path: Path) -> None:
    vault = FakeVault()
    app, server = _gated_app(tmp_path, _runtime(vault))
    update = message_update(1, chat_id=-1005, text="through the gate")
    try:
        with TestClient(app) as client:
            # The gate is really up: an admin route refuses a caller with no
            # session, and says where to sign in.
            admin = client.get("/api/session")
            # The webhook, with no session either way:
            no_secret = client.post(f"{WEBHOOK_PREFIX}/hooked", json=update)
            wrong = client.post(
                f"{WEBHOOK_PREFIX}/hooked", json=update, headers={SECRET_HEADER: "guess"}
            )
            accepted = client.post(
                f"{WEBHOOK_PREFIX}/hooked", json=update, headers={SECRET_HEADER: HOOK_SECRET}
            )
            # A session does not stand in for the secret.
            client.cookies.set(
                SESSION_COOKIE,
                server.store.create_login_session(
                    "owner", now=NOW, ttl=server.settings.session_ttl
                )[0],
            )
            signed_in_no_secret = client.post(f"{WEBHOOK_PREFIX}/hooked", json=update)
    finally:
        server.store.close()

    assert admin.status_code == 401
    assert "sign_in_url" in admin.json()

    assert no_secret.status_code == 401
    assert "sign_in_url" not in no_secret.text  # the route refused it, not the gate
    assert wrong.status_code == 401
    assert signed_in_no_secret.status_code == 401
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["delivered"] is True
    assert len(vault.captures) == 1


@pytest.mark.parametrize("path", ["/telegram/webhook/nobody", "/telegram/elsewhere"])
def test_an_unknown_telegram_path_is_a_plain_404(tmp_path: Path, path: str) -> None:
    app, server = _gated_app(tmp_path, _runtime(FakeVault()))
    try:
        with TestClient(app) as client:
            response = client.post(path, json={}, headers={SECRET_HEADER: HOOK_SECRET})
    finally:
        server.store.close()
    assert response.status_code == 404


# ------------------------------------------ bad secrets are throttled (cloud)


def test_guessing_the_webhook_secret_is_throttled_in_cloud_mode(tmp_path: Path) -> None:
    """In ``cloud``/``open`` the route is on the internet. Bad-secret ``401``s
    fill a per-caller bucket like a guessed session cookie does; the real
    sender — another caller — is unaffected, and so is the delivery."""
    vault = FakeVault()
    app = create_app(
        HubConfig(mode="cloud", host="127.0.0.1"), home=tmp_path, telegram_runtime=_runtime(vault)
    )
    guesser = TestClient(app, client=("203.0.113.9", 40000))
    telegram = TestClient(app, client=("198.51.100.7", 443))
    update = message_update(1, chat_id=-1005, text="the real one")
    url = f"{WEBHOOK_PREFIX}/hooked"

    guesses = [
        guesser.post(url, json=update, headers={SECRET_HEADER: f"guess-{n}"}).status_code
        for n in range(12)
    ]
    real = telegram.post(url, json=update, headers={SECRET_HEADER: HOOK_SECRET})
    # The guesser's window is spent, right secret or not: the limiter
    # answers before the route is reached — that is the point of it.
    late = guesser.post(url, json=update, headers={SECRET_HEADER: HOOK_SECRET})

    assert guesses[:10] == [401] * 10, guesses
    assert set(guesses[10:]) == {429}, guesses
    assert real.status_code == 200, real.text
    assert real.json()["delivered"] is True
    assert late.status_code == 429
    assert len(vault.captures) == 1


def test_real_deliveries_are_never_throttled(tmp_path: Path) -> None:
    vault = FakeVault()
    app = create_app(
        HubConfig(mode="cloud", host="127.0.0.1"), home=tmp_path, telegram_runtime=_runtime(vault)
    )
    telegram = TestClient(app, client=("198.51.100.7", 443))

    statuses = [
        telegram.post(
            f"{WEBHOOK_PREFIX}/hooked",
            json=message_update(n, chat_id=-1005, text=f"message {n}", message_id=n),
            headers={SECRET_HEADER: HOOK_SECRET},
        ).status_code
        for n in range(1, 16)
    ]

    assert statuses == [200] * 15
    assert len(vault.captures) == 15
