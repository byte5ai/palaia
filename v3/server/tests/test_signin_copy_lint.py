"""No jargon in the sign-in surface (SPEC-401 acceptance criterion #6).

``docs/design/system.md`` §3 rule 0 is binding: no protocol name, standard,
acronym, transport or implementation word in a label, heading, button, badge,
status line or option name. The sign-in page and the two refusals the session
gate can produce are the copy a locked-out operator reads, so they are linted
here the way the dashboard's own screens are linted in vitest
(``web/src/routes/Exposure.test.tsx``).

Scope, matching rule 0's own wording: the *visible* copy. Rule 0 demotes the
technical term to "hint text, a sub-line, a `title` attribute, or a
documentation link" rather than banning it, so a literal command the operator
has to type (in a ``<code>`` element inside the page's hint line) is exempt —
and markup itself (a form's ``action``, a hidden field's ``name``) is not copy
at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from palaia_hub.admin_session import CSRF_HEADER
from palaia_hub.app import create_app
from palaia_hub.config import HubConfig, OAuthSettings
from palaia_hub.oauth import AuthorizationServer, set_owner_password
from palaia_hub.oauth.login import CSRF_COOKIE, SESSION_COOKIE
from palaia_hub.vault import VaultRegistry

OWNER = "owner"
PASSWORD = "a-long-enough-passphrase"  # noqa: S105 - test fixture
NOW = 1_800_000_000

BANNED = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\boauth\b",
        r"\boidc\b",
        r"\bjwt\b",
        r"\bpkce\b",
        r"\bcimd\b",
        r"\bdcr\b",
        r"\bcsrf\b",
        r"\bbearer\b",
        r"\basgi\b",
        r"\bcookie\b",
        r"\bmiddleware\b",
        r"\btailnet\b",
        r"\brfc\s*\d",
        r"\b40[13]\b",
    )
]


def _visible_text(html: str) -> str:
    """The words a person actually reads: tags dropped, ``<code>`` dropped."""
    without_code = re.sub(r"<code>.*?</code>", " ", html, flags=re.DOTALL)
    without_head = re.sub(r"<(style|script|head)\b.*?</\1>", " ", without_code, flags=re.DOTALL)
    return re.sub(r"<[^>]+>", " ", without_head)


def _assert_plain(text: str) -> None:
    for pattern in BANNED:
        assert not pattern.search(text), f"jargon {pattern.pattern!r} in sign-in copy: {text!r}"


@dataclass
class SignInHub:
    app: FastAPI
    server: AuthorizationServer


@pytest.fixture
def hub(tmp_path: Path) -> Iterator[SignInHub]:
    config = HubConfig(
        mode="cloud",
        host="127.0.0.1",
        oauth=OAuthSettings(enabled=True, issuer="http://testserver"),
    )
    server = AuthorizationServer.build(config, {"default": ["vault:work:read"]}, home=tmp_path)
    set_owner_password(server.store, OWNER, PASSWORD, now=NOW)
    app = create_app(
        config,
        home=tmp_path,
        oauth_server=server,
        vault_registry=VaultRegistry(tmp_path / "vaults"),
    )
    try:
        yield SignInHub(app=app, server=server)
    finally:
        server.store.close()


def test_the_sign_in_page_is_plain(hub: SignInHub) -> None:
    with TestClient(hub.app, base_url="http://testserver") as client:
        page = client.get("/oauth/login")
    assert page.status_code == 200
    _assert_plain(_visible_text(page.text))


def test_a_failed_sign_in_says_so_plainly(hub: SignInHub) -> None:
    with TestClient(hub.app, base_url="http://testserver") as client:
        form = client.get("/oauth/login")
        token = form.text.split('name="csrf_token" value="')[1].split('"')[0]
        failed = client.post(
            "/oauth/login",
            data={"username": OWNER, "password": "wrong", "csrf_token": token},
            follow_redirects=False,
        )
    assert failed.status_code == 401
    _assert_plain(_visible_text(failed.text))


def test_the_two_refusals_are_plain(hub: SignInHub) -> None:
    """The "please sign in" and "could not confirm this request" answers."""
    with TestClient(hub.app, base_url="http://testserver") as client:
        unauthenticated = client.get("/api/vaults")
        assert unauthenticated.status_code == 401
        _assert_plain(unauthenticated.json()["detail"])

        session, _expires = hub.server.store.create_login_session(OWNER, now=NOW, ttl=3600)
        client.cookies.set(SESSION_COOKIE, session)
        client.cookies.set(CSRF_COOKIE, "a-token")
        no_header = client.post("/api/vaults", json={"key": "work"})
        assert no_header.status_code == 403
        _assert_plain(no_header.json()["detail"])
        # And the header name itself never appears in what the person reads.
        assert CSRF_HEADER not in no_header.text.lower()
