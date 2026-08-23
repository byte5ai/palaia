"""Client registration and the registered-client garbage collector.

MASTERPLAN §5.5's second lesson: "registered-client garbage collection —
every reconnect registers a fresh client and nothing cleans them up unless you
do." The acceptance criterion is "orphan DCR clients pruned; machine clients
never pruned", and both are checked here — along with the fences that keep a
self-registering client from talking itself into a machine identity.
"""

from __future__ import annotations

import pytest

from palaia_hub.oauth import (
    OAuthError,
    OAuthStore,
    provision_machine_client,
    register_dcr_client,
)
from palaia_hub.oauth.cimd import StaticCimdFetcher
from palaia_hub.oauth.clients import MAX_DCR_CLIENTS, resolve_client

NOW = 1_800_000_000
SCOPES = ("vault:work:read", "vault:work:write")
AUDIENCE = "https://hub.test/work"
DAY = 86400


def _register(store: OAuthStore, *, name: str = "connector", now: int = NOW) -> str:
    client = register_dcr_client(
        store,
        {"client_name": name, "redirect_uris": ["https://client.test/cb"]},
        now=now,
        allowed_scopes=SCOPES,
    )
    return client.client_id


# ------------------------------------------------------------------------ DCR


def test_dcr_creates_a_public_client_with_no_secret(store: OAuthStore) -> None:
    client_id = _register(store)
    client = store.get_client(client_id)

    assert client is not None
    assert client.source == "dcr"
    assert client.is_public is True
    assert client.is_machine is False
    assert client.client_secret_hash is None
    assert client.pinned_audience is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"redirect_uris": []},
        {"redirect_uris": ["http://not-loopback.test/cb"]},
        {"redirect_uris": ["https://client.test/cb#frag"]},
        {"redirect_uris": ["not-a-url"]},
        {"redirect_uris": ["https://client.test/cb"], "grant_types": ["client_credentials"]},
        {
            "redirect_uris": ["https://client.test/cb"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
        "not-an-object",
    ],
)
def test_dcr_rejects_metadata_it_cannot_safely_accept(store: OAuthStore, body: object) -> None:
    with pytest.raises(OAuthError):
        register_dcr_client(store, body, now=NOW, allowed_scopes=SCOPES)


def test_dcr_cannot_ask_for_the_machine_grant(store: OAuthStore) -> None:
    """MASTERPLAN §5.5: machine identities are never obtainable through DCR."""
    with pytest.raises(OAuthError) as excinfo:
        register_dcr_client(
            store,
            {
                "redirect_uris": ["https://client.test/cb"],
                "grant_types": ["authorization_code", "client_credentials"],
            },
            now=NOW,
            allowed_scopes=SCOPES,
        )

    assert excinfo.value.error == "invalid_client_metadata"
    assert "operator" in excinfo.value.description


def test_http_loopback_redirect_is_allowed_for_native_clients(store: OAuthStore) -> None:
    client = register_dcr_client(
        store,
        {"redirect_uris": ["http://127.0.0.1:7777/callback"]},
        now=NOW,
        allowed_scopes=SCOPES,
    )

    assert client.redirect_uris == ("http://127.0.0.1:7777/callback",)


def test_the_dcr_ceiling_refuses_further_registrations(store: OAuthStore) -> None:
    for index in range(MAX_DCR_CLIENTS):
        _register(store, name=f"c{index}")

    with pytest.raises(OAuthError) as excinfo:
        _register(store, name="one-too-many")

    assert "CIMD" in excinfo.value.description


# ----------------------------------------------------------------------- CIMD


@pytest.mark.anyio
async def test_a_cimd_client_id_registers_itself_on_first_use(store: OAuthStore) -> None:
    client_id = "https://client.test/app.json"
    fetcher = StaticCimdFetcher(
        {
            client_id: {
                "client_id": client_id,
                "client_name": "CIMD connector",
                "redirect_uris": ["https://client.test/cb"],
            }
        }
    )

    client = await resolve_client(store, fetcher, client_id, now=NOW, allowed_scopes=SCOPES)

    assert client.source == "cimd"
    assert client.client_id == client_id
    assert store.get_client(client_id) is not None


@pytest.mark.anyio
async def test_a_reconnect_reuses_the_same_cimd_row(store: OAuthStore) -> None:
    """The whole point of CIMD: reconnects do not accumulate client rows."""
    client_id = "https://client.test/app.json"
    fetcher = StaticCimdFetcher(
        {client_id: {"client_id": client_id, "redirect_uris": ["https://client.test/cb"]}}
    )

    for offset in range(5):
        await resolve_client(
            store, fetcher, client_id, now=NOW + offset, allowed_scopes=SCOPES
        )

    assert store.count_clients() == 1
    assert store.get_client(client_id).created_at == NOW  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_a_refetched_document_updates_the_redirect_uris(store: OAuthStore) -> None:
    client_id = "https://client.test/app.json"
    fetcher = StaticCimdFetcher(
        {client_id: {"client_id": client_id, "redirect_uris": ["https://client.test/old"]}}
    )
    await resolve_client(store, fetcher, client_id, now=NOW, allowed_scopes=SCOPES)

    fetcher.documents[client_id] = {
        "client_id": client_id,
        "redirect_uris": ["https://client.test/new"],
    }
    client = await resolve_client(store, fetcher, client_id, now=NOW + 1, allowed_scopes=SCOPES)

    assert client.redirect_uris == ("https://client.test/new",)


@pytest.mark.anyio
async def test_an_unreachable_document_falls_back_to_the_stored_row(
    store: OAuthStore,
) -> None:
    client_id = "https://client.test/app.json"
    fetcher = StaticCimdFetcher(
        {client_id: {"client_id": client_id, "redirect_uris": ["https://client.test/cb"]}}
    )
    await resolve_client(store, fetcher, client_id, now=NOW, allowed_scopes=SCOPES)
    fetcher.documents.clear()

    client = await resolve_client(store, fetcher, client_id, now=NOW + 1, allowed_scopes=SCOPES)

    assert client.redirect_uris == ("https://client.test/cb",)


@pytest.mark.anyio
async def test_an_unknown_client_id_is_invalid_client(store: OAuthStore) -> None:
    with pytest.raises(OAuthError) as excinfo:
        await resolve_client(
            store, StaticCimdFetcher(), "dcr_nothing", now=NOW, allowed_scopes=SCOPES
        )

    assert excinfo.value.error == "invalid_client"


# ------------------------------------------------------------ machine clients


def test_a_machine_client_is_confidential_and_pinned(store: OAuthStore) -> None:
    provisioned = provision_machine_client(
        store, client_name="nightly job", audience=AUDIENCE, scopes=SCOPES, now=NOW
    )
    client = store.get_client(provisioned.client.client_id)

    assert client is not None
    assert client.is_machine is True
    assert client.source == "admin"
    assert client.pinned_audience == AUDIENCE
    assert client.grant_types == ("client_credentials",)
    # The secret is returned once and only its argon2id hash is stored.
    assert client.client_secret_hash is not None
    assert client.client_secret_hash.startswith("$argon2id$")
    assert provisioned.client_secret not in client.client_secret_hash


def test_a_machine_client_needs_a_name_and_a_scope(store: OAuthStore) -> None:
    with pytest.raises(OAuthError):
        provision_machine_client(
            store, client_name="", audience=AUDIENCE, scopes=SCOPES, now=NOW
        )
    with pytest.raises(OAuthError):
        provision_machine_client(
            store, client_name="job", audience=AUDIENCE, scopes=[], now=NOW
        )


# ------------------------------------------------------------------------- GC


def test_an_orphaned_dcr_client_is_pruned(store: OAuthStore) -> None:
    client_id = _register(store, now=NOW)

    report = store.prune_clients(
        now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.ran is True
    assert report.pruned == [client_id]
    assert store.get_client(client_id) is None


def test_a_recently_seen_client_is_kept(store: OAuthStore) -> None:
    client_id = _register(store, now=NOW)
    store.touch_client(client_id, NOW + 30 * DAY)

    report = store.prune_clients(
        now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.pruned == []
    assert store.get_client(client_id) is not None


def test_a_client_holding_a_live_refresh_token_is_kept_however_old(
    store: OAuthStore,
) -> None:
    client_id = _register(store, now=NOW)
    code = store.create_code(
        client_id=client_id,
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience=AUDIENCE,
        subject="owner",
        scopes=SCOPES,
        now=NOW,
        ttl=60,
    )
    _row, grant = store.exchange_code(code, NOW)
    store.issue_refresh_token(grant=grant, now=NOW, ttl=365 * DAY)
    # Age the client back out again: it is stale but not orphaned.
    store.touch_client(client_id, NOW)

    report = store.prune_clients(
        now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.pruned == []


def test_a_client_whose_grant_was_revoked_becomes_prunable(store: OAuthStore) -> None:
    client_id = _register(store, now=NOW)
    code = store.create_code(
        client_id=client_id,
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience=AUDIENCE,
        subject="owner",
        scopes=SCOPES,
        now=NOW,
        ttl=60,
    )
    _row, grant = store.exchange_code(code, NOW)
    store.issue_refresh_token(grant=grant, now=NOW, ttl=365 * DAY)
    store.revoke_grant(grant.grant_id, NOW + 1)
    store.touch_client(client_id, NOW)

    report = store.prune_clients(
        now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.pruned == [client_id]


def test_a_machine_client_is_never_pruned(store: OAuthStore) -> None:
    """It has no refresh token by design, so "orphaned" must not include it."""
    provisioned = provision_machine_client(
        store, client_name="nightly job", audience=AUDIENCE, scopes=SCOPES, now=NOW
    )

    report = store.prune_clients(
        now=NOW + 10 * 365 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.pruned == []
    assert report.kept_machine == 1
    assert store.get_client(provisioned.client.client_id) is not None


def test_a_cimd_client_is_prunable_too(store: OAuthStore) -> None:
    """A cached CIMD row is a cache: pruning it costs one re-fetch, nothing more."""
    from palaia_hub.oauth.models import ClientRow

    store.put_client(
        ClientRow(
            client_id="https://client.test/app.json",
            source="cimd",
            client_name="cimd client",
            redirect_uris=("https://client.test/cb",),
            grant_types=("authorization_code",),
            scopes=SCOPES,
            created_at=NOW,
            last_seen_at=NOW,
        )
    )

    report = store.prune_clients(
        now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert report.pruned == ["https://client.test/app.json"]


def test_the_gc_is_throttled(store: OAuthStore) -> None:
    _register(store, now=NOW)

    first = store.prune_clients(now=NOW + 31 * DAY, ttl_seconds=30 * DAY, throttle_seconds=3600)
    second = store.prune_clients(
        now=NOW + 31 * DAY + 10, ttl_seconds=30 * DAY, throttle_seconds=3600
    )
    third = store.prune_clients(
        now=NOW + 31 * DAY + 3601, ttl_seconds=30 * DAY, throttle_seconds=3600
    )

    assert first.ran is True
    assert second.ran is False, "a second pass inside the throttle window must not run"
    assert third.ran is True


def test_force_bypasses_the_throttle_for_the_cli(store: OAuthStore) -> None:
    store.prune_clients(now=NOW, ttl_seconds=30 * DAY, throttle_seconds=3600)

    report = store.prune_clients(
        now=NOW + 1, ttl_seconds=30 * DAY, throttle_seconds=3600, force=True
    )

    assert report.ran is True
