"""Grace-windowed refresh rotation — the daily-re-login incident, as tests.

MASTERPLAN §5.5 records the failure this file exists to prevent: strict
single-use rotation, plus a claude.ai connector fanned out over web, phone and
desktop, produced concurrent refreshes that tore the grant down and forced a
re-login every day. The acceptance criterion is "two concurrent refreshes of
one grant converge (no invalid_grant chain teardown); after the grace window
the spent token is dead", and both halves are checked here at the store level;
``test_token_endpoint.py`` checks the same behaviour through HTTP, and
``test_concurrency_fanout.py`` checks it under real thread contention.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from palaia_hub.oauth import OAuthError, OAuthStore
from palaia_hub.oauth.models import GrantRow
from palaia_hub.oauth.store import MAX_GRACE_SUCCESSORS

NOW = 1_800_000_000
TTL = 3600
GRACE = 120


def _grant(store: OAuthStore, *, now: int = NOW) -> GrantRow:
    code = store.create_code(
        client_id="c1",
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience="https://hub.test/work",
        subject="owner",
        scopes=["vault:work:read", "vault:work:write"],
        now=now,
        ttl=60,
    )
    _row, grant = store.exchange_code(code, now)
    return grant


def test_a_live_token_rotates_into_a_working_successor(store: OAuthStore) -> None:
    grant = _grant(store)
    first, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    outcome = store.rotate_refresh_token(first, now=NOW, ttl=TTL, grace_window=GRACE)

    assert outcome.replayed is False
    assert outcome.grant.grant_id == grant.grant_id
    assert outcome.refresh_token != first
    # The successor itself rotates, so the chain continues.
    again = store.rotate_refresh_token(
        outcome.refresh_token, now=NOW + 1, ttl=TTL, grace_window=GRACE
    )
    assert again.grant.grant_id == grant.grant_id


def test_two_concurrent_refreshes_of_one_grant_both_succeed(store: OAuthStore) -> None:
    """The fan-out case: no invalid_grant, no chain teardown, both usable."""
    grant = _grant(store)
    shared, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    first = store.rotate_refresh_token(shared, now=NOW, ttl=TTL, grace_window=GRACE)
    second = store.rotate_refresh_token(shared, now=NOW + 3, ttl=TTL, grace_window=GRACE)

    assert first.replayed is False
    assert second.replayed is True
    assert first.refresh_token != second.refresh_token
    # Both successors are live credentials for the same, un-revoked grant.
    assert store.get_grant(grant.grant_id) is not None
    assert store.get_grant(grant.grant_id).revoked_at is None  # type: ignore[union-attr]
    for successor in (first.refresh_token, second.refresh_token):
        outcome = store.rotate_refresh_token(successor, now=NOW + 5, ttl=TTL, grace_window=GRACE)
        assert outcome.grant.grant_id == grant.grant_id


def test_a_replay_cannot_extend_its_own_grace_window(store: OAuthStore) -> None:
    """``COALESCE`` keeps the *first* ``grace_until``, so the window is finite."""
    grant = _grant(store)
    shared, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    store.rotate_refresh_token(shared, now=NOW, ttl=TTL, grace_window=GRACE)
    for offset in (30, 60, 90, 119):
        store.rotate_refresh_token(shared, now=NOW + offset, ttl=TTL, grace_window=GRACE)

    row = store.get_refresh_token(shared)
    assert row is not None
    assert row.grace_until == NOW + GRACE

    with pytest.raises(OAuthError) as excinfo:
        store.rotate_refresh_token(shared, now=NOW + GRACE + 1, ttl=TTL, grace_window=GRACE)
    assert excinfo.value.error == "invalid_grant"


def test_after_the_grace_window_the_spent_token_is_dead(store: OAuthStore) -> None:
    grant = _grant(store)
    spent, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    successor = store.rotate_refresh_token(spent, now=NOW, ttl=TTL, grace_window=GRACE)

    with pytest.raises(OAuthError) as excinfo:
        store.rotate_refresh_token(spent, now=NOW + GRACE + 1, ttl=TTL, grace_window=GRACE)

    assert excinfo.value.error == "invalid_grant"
    # Issue #346 reversed the earlier choice here: a spent token presented
    # after its window is a kept copy, so the family goes with it — the
    # successor the legitimate client holds is dead too, and that client
    # re-authorizes once. (Inside the window, fan-out still converges: see
    # test_two_concurrent_refreshes_of_one_grant_both_succeed.)
    with pytest.raises(OAuthError):
        store.rotate_refresh_token(
            successor.refresh_token, now=NOW + GRACE + 2, ttl=TTL, grace_window=GRACE
        )
    assert store.get_grant(grant.grant_id).revoked_at == NOW + GRACE + 1  # type: ignore[union-attr]


def test_a_replay_after_the_grace_window_revokes_the_whole_family(store: OAuthStore) -> None:
    """Issue #346, RFC 9700 §4.14.2: a spent token presented after its window
    is a kept copy, not a surface fanning out. The grant and every successor
    it produced die with it — the copy is worthless from then on."""
    grant = _grant(store)
    spent, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    first = store.rotate_refresh_token(spent, now=NOW, ttl=TTL, grace_window=GRACE)
    second = store.rotate_refresh_token(spent, now=NOW + 5, ttl=TTL, grace_window=GRACE)

    with pytest.raises(OAuthError):
        store.rotate_refresh_token(spent, now=NOW + GRACE + 1, ttl=TTL, grace_window=GRACE)

    assert store.get_grant(grant.grant_id).revoked_at == NOW + GRACE + 1  # type: ignore[union-attr]
    for successor in (first.refresh_token, second.refresh_token):
        with pytest.raises(OAuthError):
            store.rotate_refresh_token(successor, now=NOW + GRACE + 2, ttl=TTL, grace_window=GRACE)


def test_too_many_replays_inside_the_grace_window_revoke_the_family(store: OAuthStore) -> None:
    """Fan-out needs a handful of successors; a token presented eight times
    within seconds is being replayed under cover of the window."""
    grant = _grant(store)
    spent, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    successors = [
        store.rotate_refresh_token(spent, now=NOW + index, ttl=TTL, grace_window=GRACE)
        for index in range(MAX_GRACE_SUCCESSORS)
    ]
    assert len({s.refresh_token for s in successors}) == MAX_GRACE_SUCCESSORS
    assert store.get_grant(grant.grant_id).revoked_at is None  # type: ignore[union-attr]

    with pytest.raises(OAuthError):
        store.rotate_refresh_token(
            spent, now=NOW + MAX_GRACE_SUCCESSORS, ttl=TTL, grace_window=GRACE
        )

    assert store.get_grant(grant.grant_id).revoked_at is not None  # type: ignore[union-attr]
    with pytest.raises(OAuthError):
        store.rotate_refresh_token(
            successors[0].refresh_token, now=NOW + 20, ttl=TTL, grace_window=GRACE
        )


def test_a_zero_grace_window_is_strict_single_use(store: OAuthStore) -> None:
    """The setting that caused the incident, still available and still honest."""
    grant = _grant(store)
    token, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    store.rotate_refresh_token(token, now=NOW, ttl=TTL, grace_window=0)

    with pytest.raises(OAuthError):
        store.rotate_refresh_token(token, now=NOW + 1, ttl=TTL, grace_window=0)


def test_an_expired_token_never_rotates(store: OAuthStore) -> None:
    grant = _grant(store)
    token, expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    with pytest.raises(OAuthError):
        store.rotate_refresh_token(token, now=expiry + 1, ttl=TTL, grace_window=GRACE)


def test_revoking_the_grant_kills_every_token_in_the_family(store: OAuthStore) -> None:
    grant = _grant(store)
    first, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    second = store.rotate_refresh_token(first, now=NOW, ttl=TTL, grace_window=GRACE)

    store.revoke_grant(grant.grant_id, NOW + 1)

    for token in (first, second.refresh_token):
        with pytest.raises(OAuthError):
            store.rotate_refresh_token(token, now=NOW + 2, ttl=TTL, grace_window=GRACE)


def test_revoking_by_token_revokes_the_whole_grant(store: OAuthStore) -> None:
    grant = _grant(store)
    token, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    successor = store.rotate_refresh_token(token, now=NOW, ttl=TTL, grace_window=GRACE)

    assert store.revoke_refresh_token(successor.refresh_token, NOW + 1) is True

    with pytest.raises(OAuthError):
        store.rotate_refresh_token(token, now=NOW + 2, ttl=TTL, grace_window=GRACE)
    # RFC 7009 §2.2: an unknown token is not an error.
    assert store.revoke_refresh_token("not-a-token", NOW + 1) is False


def test_an_unknown_token_is_the_same_error_as_a_revoked_one(store: OAuthStore) -> None:
    grant = _grant(store)
    token, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)
    store.revoke_grant(grant.grant_id, NOW)

    errors = []
    for candidate in ("completely-unknown-token", token):
        with pytest.raises(OAuthError) as excinfo:
            store.rotate_refresh_token(candidate, now=NOW + 1, ttl=TTL, grace_window=GRACE)
        errors.append((excinfo.value.error, excinfo.value.description))

    assert errors[0] == errors[1], "the failure reason must not be distinguishable"


def test_real_thread_contention_on_one_token_never_corrupts_the_chain(
    store: OAuthStore,
) -> None:
    """Six threads, one shared token: every result is a usable, same-grant token."""
    grant = _grant(store)
    shared, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    def rotate() -> str:
        return store.rotate_refresh_token(
            shared, now=NOW, ttl=TTL, grace_window=GRACE
        ).refresh_token

    with ThreadPoolExecutor(max_workers=6) as pool:
        successors = [future.result() for future in [pool.submit(rotate) for _ in range(6)]]

    assert len(set(successors)) == 6
    for successor in successors:
        row = store.get_refresh_token(successor)
        assert row is not None and row.grant_id == grant.grant_id
    assert store.get_grant(grant.grant_id).revoked_at is None  # type: ignore[union-attr]


def test_authorization_code_replay_revokes_its_grant(store: OAuthStore) -> None:
    """Codes get textbook replay handling; only refresh tokens get a grace window."""
    code = store.create_code(
        client_id="c1",
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience="https://hub.test/work",
        subject="owner",
        scopes=["vault:work:read"],
        now=NOW,
        ttl=60,
    )
    _row, grant = store.exchange_code(code, NOW)
    refresh, _expiry = store.issue_refresh_token(grant=grant, now=NOW, ttl=TTL)

    with pytest.raises(OAuthError) as excinfo:
        store.exchange_code(code, NOW + 1)

    assert excinfo.value.error == "invalid_grant"
    assert store.get_grant(grant.grant_id).revoked_at == NOW + 1  # type: ignore[union-attr]
    with pytest.raises(OAuthError):
        store.rotate_refresh_token(refresh, now=NOW + 2, ttl=TTL, grace_window=GRACE)


def test_an_expired_code_is_refused(store: OAuthStore) -> None:
    code = store.create_code(
        client_id="c1",
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience="https://hub.test/work",
        subject="owner",
        scopes=["vault:work:read"],
        now=NOW,
        ttl=60,
    )

    with pytest.raises(OAuthError):
        store.exchange_code(code, NOW + 61)
