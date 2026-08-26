"""Shared scaffolding for the SPEC-502 hardening suite.

One builder, :func:`build_hub`, assembles a hub with as much of the real
surface attached as a test process can hold — every REST router, the OAuth
server, the session gate — because the point of most of these tests is
coverage of the *whole* surface rather than of one endpoint.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI

from palaia_hub.app import create_app
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import DashboardSettings, HubConfig, OAuthSettings
from palaia_hub.hooks import HookOutbox, HookStore
from palaia_hub.notifications import NotificationStore
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.vault import VaultRegistry

ISSUER = "https://hub.example.test"
OWNER = "owner"
PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
NOW = 1_800_000_000


@dataclass
class Hub:
    """An assembled app plus the pieces a test needs to drive it."""

    app: FastAPI
    server: AuthorizationServer
    home: Path

    def session_cookie(self) -> str:
        session, _expires = self.server.store.create_login_session(
            OWNER, now=NOW, ttl=self.server.settings.session_ttl
        )
        return session


def build_hub(
    home: Path,
    *,
    mode: str = "cloud",
    require_sign_in: bool | None = None,
    with_owner: bool = True,
) -> Hub:
    config = HubConfig(
        mode=mode,  # type: ignore[arg-type]
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer=ISSUER),
        dashboard=DashboardSettings(require_sign_in=require_sign_in),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=home)
    if with_owner:
        set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    app = create_app(
        config,
        home=home,
        oauth_server=server,
        vault_registry=VaultRegistry(home / "vaults"),
        token_store=TokenStore(home=home),
        hook_store=HookStore(home),
        hook_outbox=HookOutbox(home / "hook-outbox.sqlite3"),
        notification_store=NotificationStore(home / "notifications.sqlite3"),
    )
    return Hub(app=app, server=server, home=home)


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[Hub]:
    built = build_hub(tmp_path)
    try:
        yield built
    finally:
        built.server.store.close()
