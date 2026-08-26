"""SPEC-504 deliverable #2's error-message audit, made a real regression
test: every failure branch a first-timer can actually hit while walking the
funnel (create vault -> connect a client -> write the first memory) must
name its fix, not just describe what went wrong.

This walks the branches through the real HTTP/REST surface (never
constructs the underlying exception directly), so a test here proves the
*response a browser actually receives* names the fix — not just that some
internal exception class happens to have good wording that a handler could
still discard on the way out.

The "names the fix" bar this suite applies: the message contains the literal
word ``Fix`` (this codebase's own consistent convention throughout
``palaia_hub.vault.errors``/``palaia_hub.auth.store`` — see either module)
*or* an imperative verb phrase telling the reader what to do next
(``check``, ``pick``, ``use``, ``create``, ``try again``, ...) — deliberately
not just "contains a colon" or some other structural proxy that a vague
restatement of the error could satisfy by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from palaia_hub.app import create_app
from palaia_hub.auth.enforcement import missing_scope_error
from palaia_hub.auth.store import TokenStore
from palaia_hub.config import HubConfig
from palaia_hub.vault import EventBus as VaultEventBus
from palaia_hub.vault import VaultRegistry

_FIX_VERBS = re.compile(
    r"\bfix\b|\bcheck\b|\bpick\b|\buse\b|\bcreate\b|\btry again\b|\brename\b|\bgive\b|"
    r"\bpass\b|\bcorrect\b|\bdelete\b",
    re.IGNORECASE,
)


def _names_a_fix(message: str) -> bool:
    return bool(_FIX_VERBS.search(message))


def test_create_vault_with_an_invalid_key_names_the_fix(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "registry", bus=VaultEventBus())
    app = create_app(
        HubConfig(), vault_registry=registry, vault_services={}, home=tmp_path / "home"
    )
    client = TestClient(app)

    response = client.post("/api/vaults", json={"key": "Not A Valid Key!"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert _names_a_fix(detail), f"does not name a fix: {detail!r}"


def test_create_vault_with_a_key_already_taken_names_the_fix(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path / "registry", bus=VaultEventBus())
    app = create_app(
        HubConfig(), vault_registry=registry, vault_services={}, home=tmp_path / "home"
    )
    client = TestClient(app)
    first = client.post("/api/vaults", json={"key": "work"})
    assert first.status_code == 200

    response = client.post("/api/vaults", json={"key": "work"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert _names_a_fix(detail), f"does not name a fix: {detail!r}"


def test_create_token_with_an_invalid_scope_names_the_fix(tmp_path: Path) -> None:
    app = create_app(HubConfig(), token_store=TokenStore(home=tmp_path), home=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/auth/tokens",
        json={"name": "a", "profile": "default", "scopes": ["not-a-real-scope"]},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert _names_a_fix(detail), f"does not name a fix: {detail!r}"


def test_create_token_with_an_empty_name_names_the_fix(tmp_path: Path) -> None:
    app = create_app(HubConfig(), token_store=TokenStore(home=tmp_path), home=tmp_path)
    client = TestClient(app)

    response = client.post("/api/auth/tokens", json={"name": "", "profile": "default"})

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert _names_a_fix(detail), f"does not name a fix: {detail!r}"


def test_missing_scope_tool_error_names_the_fix() -> None:
    """The read-only-scoped-token-hits-the-write-tool shape (the concrete
    failure a wizard-issued token with a narrower explicit scope than its
    profile's vaults would hit): calls the real
    :func:`~palaia_hub.auth.enforcement.missing_scope_error` the memory
    tools call, with a real ``AccessToken`` set on the same context var
    fastmcp's own HTTP auth middleware sets it on in production — the
    in-process route this file's other tests use
    (:class:`fastmcp.client.transports.FastMCPTransport`, via
    ``Client(a_fastmcp_server_instance)``) explicitly refuses an ``auth=``
    argument, so a real end-to-end HTTP round trip is what
    ``tests/e2e/test_s7_spec504_first_run_funnel.py`` covers instead — this
    is the fast, direct check of the message the two together
    complement."""
    access_token = AccessToken(
        token="plt_test", client_id="read-only-client", scopes=["vault:work:read"]
    )
    reset = auth_context_var.set(AuthenticatedUser(access_token))
    try:
        message = missing_scope_error("work", "write")
    finally:
        auth_context_var.reset(reset)

    assert message is not None
    assert _names_a_fix(message), message
    assert "vault:work:write" in message
