"""The six-connector refresh fan-out — the mcp-hub daily-re-login incident.

The required regression test from SPEC-203 deliverable #5: "a concurrency
regression test simulating the 6-connector refresh fan-out (the mcp-hub
daily-re-login incident) is REQUIRED", with the acceptance criterion
"concurrency fan-out test: no 500s, no store corruption".

What makes this test real rather than decorative: ``/oauth/token`` runs the
whole grant through ``asyncio.to_thread`` (see
:meth:`palaia_hub.oauth.service.AuthorizationServer.token`), so N simultaneous
requests really are N threads contending for the store's single connection and
lock. If the ``BEGIN IMMEDIATE`` discipline in
:mod:`palaia_hub.oauth.store` were wrong — a deferred transaction, a
connection per request, a read-then-write split across two transactions — this
is where it would show up, as an ``OperationalError`` surfacing as a 500 or as
two callers rotating the same row.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from palaia_hub.oauth.pkce import challenge_for

from .harness import (
    CIMD_CLIENT_ID,
    CIMD_REDIRECT_URI,
    OWNER_PASSWORD,
    OWNER_USERNAME,
    Harness,
    authorize_with_consent,
)

BASE_URL = "https://testserver"
CONNECTORS = 6
SURFACES_PER_CONNECTOR = 3


def _http(harness: Harness) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=harness.app),
        base_url=BASE_URL,
        follow_redirects=False,
        timeout=30.0,
    )


async def _sign_in(http: httpx.AsyncClient) -> None:
    await http.get("/oauth/login")
    response = await http.post(
        "/oauth/login",
        data={
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
            "csrf_token": http.cookies["palaia_oauth_csrf"],
            "next": "",
        },
    )
    assert response.status_code == 303, response.text


async def _one_grant(harness: Harness, http: httpx.AsyncClient, index: int) -> str:
    """Run the code flow once; return the grant's first refresh token."""
    verifier = f"connector-{index}-verifier-padded-to-the-minimum-length"
    authorize = await authorize_with_consent(
        http,
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": CIMD_CLIENT_ID,
            "redirect_uri": CIMD_REDIRECT_URI,
            "code_challenge": challenge_for(verifier),
            "code_challenge_method": "S256",
            "resource": harness.audience("alpha" if index % 2 == 0 else "beta"),
        },
    )
    assert authorize.status_code == 303, authorize.text
    code = httpx.URL(authorize.headers["location"]).params["code"]
    response = await http.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": CIMD_CLIENT_ID,
            "redirect_uri": CIMD_REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["refresh_token"])


def test_the_store_has_the_connection_discipline_it_documents(harness: Harness) -> None:
    """One connection, WAL, immediate transactions — pinned, not assumed.

    Deliverable #5 is "hub-level SQLite with explicit connection/locking
    discipline". The fan-out tests below prove the *behaviour*; this one pins
    the mechanism, so a later change that quietly swaps in a connection pool
    or a deferred transaction fails here with an explanation instead of
    failing intermittently under load.
    """
    import sqlite3
    import threading

    store = harness.store
    assert isinstance(store._conn, sqlite3.Connection)  # noqa: SLF001 - mechanism assertion
    assert isinstance(store._lock, type(threading.RLock()))  # noqa: SLF001
    # isolation_level=None: this module owns its BEGIN/COMMIT, not sqlite3.
    assert store._conn.isolation_level is None  # noqa: SLF001
    journal = store._conn.execute("PRAGMA journal_mode").fetchone()[0]  # noqa: SLF001
    assert journal.lower() == "wal"
    busy = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]  # noqa: SLF001
    assert busy >= 5000

    source = (Path(__file__).parents[2] / "src/palaia_hub/oauth/store.py").read_text()
    assert 'conn.execute("BEGIN IMMEDIATE")' in source


@pytest.mark.anyio
async def test_six_connectors_fanned_out_over_three_surfaces_each(harness: Harness) -> None:
    """18 simultaneous refreshes across 6 grants: every one succeeds."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            refresh_tokens = [await _one_grant(harness, http, index) for index in range(CONNECTORS)]

            async def refresh(token: str) -> httpx.Response:
                return await http.post(
                    "/oauth/token",
                    data={"grant_type": "refresh_token", "refresh_token": token},
                )

            # Each connector's stored refresh token, presented from three
            # surfaces at the same moment — the exact shape of the incident.
            responses = await asyncio.gather(
                *[refresh(token) for token in refresh_tokens for _ in range(SURFACES_PER_CONNECTOR)]
            )

            statuses = sorted({response.status_code for response in responses})
            assert statuses == [200], [
                (response.status_code, response.text) for response in responses
            ]
            assert not any(response.status_code >= 500 for response in responses)

            # Every response carried a usable, distinct successor.
            successors = [str(response.json()["refresh_token"]) for response in responses]
            assert len(set(successors)) == len(successors)

            # The store is intact: each successor names a live grant, and no
            # grant in the fan-out was revoked.
            grant_ids = set()
            for successor in successors:
                row = harness.store.get_refresh_token(successor)
                assert row is not None
                grant = harness.store.get_grant(row.grant_id)
                assert grant is not None and grant.revoked_at is None
                grant_ids.add(row.grant_id)
            assert len(grant_ids) == CONNECTORS

            # And every successor still works afterwards — no chain teardown.
            second_round = await asyncio.gather(*[refresh(token) for token in successors])
            assert {response.status_code for response in second_round} == {200}


@pytest.mark.anyio
async def test_the_store_survives_mixed_concurrent_traffic(harness: Harness) -> None:
    """Refreshes, registrations, revocations and reads at once: no 5xx."""
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            tokens = [await _one_grant(harness, http, index) for index in range(3)]

            async def refresh(token: str) -> httpx.Response:
                return await http.post(
                    "/oauth/token",
                    data={"grant_type": "refresh_token", "refresh_token": token},
                )

            async def register(index: int) -> httpx.Response:
                return await http.post(
                    "/oauth/register",
                    json={
                        "client_name": f"burst-{index}",
                        "redirect_uris": [f"https://client.test/cb/{index}"],
                    },
                )

            async def revoke(token: str) -> httpx.Response:
                return await http.post("/oauth/revoke", data={"token": token})

            async def metadata() -> httpx.Response:
                return await http.get("/.well-known/oauth-authorization-server")

            responses = await asyncio.gather(
                *(
                    [refresh(token) for token in tokens for _ in range(3)]
                    + [register(index) for index in range(6)]
                    + [revoke(tokens[-1]) for _ in range(3)]
                    + [metadata() for _ in range(6)]
                ),
                return_exceptions=True,
            )

    assert not any(isinstance(response, BaseException) for response in responses), responses
    codes = [response.status_code for response in responses]  # type: ignore[union-attr]
    assert not any(code >= 500 for code in codes), codes
    # The registrations all landed, so nothing was lost to contention.
    assert harness.store.count_clients(source="dcr") == 6


@pytest.mark.anyio
async def test_concurrent_code_redemption_yields_exactly_one_winner(
    harness: Harness,
) -> None:
    """One code, three simultaneous exchanges: one 200, the rest invalid_grant."""
    verifier = "single-use-code-verifier-padded-to-the-minimum-len"
    async with harness.app.router.lifespan_context(harness.app):
        async with _http(harness) as http:
            await _sign_in(http)
            authorize = await authorize_with_consent(
                http,
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": CIMD_CLIENT_ID,
                    "redirect_uri": CIMD_REDIRECT_URI,
                    "code_challenge": challenge_for(verifier),
                    "code_challenge_method": "S256",
                    "resource": harness.audience("alpha"),
                },
            )
            code = httpx.URL(authorize.headers["location"]).params["code"]

            async def exchange() -> httpx.Response:
                return await http.post(
                    "/oauth/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": CIMD_CLIENT_ID,
                        "redirect_uri": CIMD_REDIRECT_URI,
                        "code_verifier": verifier,
                    },
                )

            responses = await asyncio.gather(exchange(), exchange(), exchange())

    codes = [response.status_code for response in responses]
    assert codes.count(200) == 1, codes
    assert not any(code >= 500 for code in codes), codes
    for response in responses:
        if response.status_code != 200:
            assert response.json()["error"] == "invalid_grant"
