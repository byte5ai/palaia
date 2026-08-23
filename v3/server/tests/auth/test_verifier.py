"""PalaiaTokenVerifier: the fastmcp-facing adapter, including profile binding."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.verifier import PalaiaTokenVerifier


@pytest.mark.anyio
async def test_valid_token_for_its_own_profile_verifies(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", ["vault:work:read", "vault:work:write"])
    verifier = PalaiaTokenVerifier(store, "default")

    access_token = await verifier.verify_token(created.token)

    assert access_token is not None
    assert access_token.client_id == created.info.id
    assert set(access_token.scopes) == {"vault:work:read", "vault:work:write"}
    assert access_token.subject == "client"


@pytest.mark.anyio
async def test_token_bound_to_profile_a_is_rejected_by_profile_b(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "profile-a", ["vault:work:read"])
    verifier_b = PalaiaTokenVerifier(store, "profile-b")

    assert await verifier_b.verify_token(created.token) is None

    # The matching profile's verifier still accepts it.
    verifier_a = PalaiaTokenVerifier(store, "profile-a")
    assert await verifier_a.verify_token(created.token) is not None


@pytest.mark.anyio
async def test_revoked_token_is_rejected(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    store.revoke(created.info.id)
    verifier = PalaiaTokenVerifier(store, "default")

    assert await verifier.verify_token(created.token) is None


@pytest.mark.anyio
async def test_garbage_token_is_rejected(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    verifier = PalaiaTokenVerifier(store, "default")

    assert await verifier.verify_token("garbage") is None
