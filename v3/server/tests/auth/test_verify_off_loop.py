"""Issue #608: client-token verification must not block the event loop.

Every bearer token presented on the public MCP surface used to be checked
with a synchronous argon2 verify inside the async verifier — including a
dummy verify for tokens that are not even shaped like a palaia token. Twenty
invalid tokens held up a 10 ms timer for almost three seconds, starving the
health check, the dashboard and every authorized client on the same loop.

The contract these tests pin:

* the expensive argon2 work runs off the event loop, on a small bounded pool;
* a token that is not shaped like a palaia token costs no argon2 at all (the
  token format is public, so skipping it reveals nothing);
* a client that already verified keeps verifying fast while a flood of bad
  tokens is queued — and a revoked token is refused at once regardless.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

import palaia_hub.auth.store as store_module
from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.verifier import HubTokenVerifier, PalaiaTokenVerifier

pytestmark = pytest.mark.anyio

# Well-formed (prefix, id, secret) but never issued: each one costs a real
# argon2 verify (the dummy one that hides whether the id exists).
UNKNOWN = [f"plt_unknownid{i:04d}.{'s' * 24}{i:04d}" for i in range(20)]
# Not shaped like a palaia token at all.
MALFORMED = ["not-a-token", "", "Bearer", "x" * 64, "plt_short.s"]


async def _tick_delay(start_work: Callable[[], Awaitable[object]]) -> tuple[float, object]:
    """How late a 10 ms timer fires when ``start_work`` starts right after it."""

    async def tick() -> float:
        started = time.perf_counter()
        await asyncio.sleep(0.01)
        return time.perf_counter() - started

    timer = asyncio.create_task(tick())
    await asyncio.sleep(0)  # the timer is armed before any of the work is scheduled
    result = await start_work()
    return await timer, result


async def test_invalid_tokens_do_not_hold_up_the_event_loop(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    store.create("client", "default", ["vault:work:read"])
    verifier = HubTokenVerifier(store)

    delay, results = await _tick_delay(
        lambda: asyncio.gather(*(verifier.verify_token(t) for t in UNKNOWN + MALFORMED))
    )

    assert all(result is None for result in results)  # type: ignore[attr-defined]
    # Synchronous argon2 on the loop puts this well past a second; off the
    # loop the timer fires on time give or take scheduling noise.
    assert delay < 0.3, f"a 10 ms timer fired {delay:.3f}s late"


async def test_a_malformed_token_costs_no_argon2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(store_module, "spend_constant_time_miss", lambda: calls.append("miss"))
    store = TokenStore(home=tmp_path)
    verifier = HubTokenVerifier(store)

    for token in MALFORMED:
        assert await verifier.verify_token(token) is None
    assert calls == [], "a token the format already rules out must not spend argon2"

    # A well-formed token with an unknown id still pays the dummy verify, so
    # "no such id" costs the same as "wrong secret".
    assert await verifier.verify_token(UNKNOWN[0]) is None
    assert calls == ["miss"]


async def test_argon2_runs_on_a_small_bounded_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = threading.Lock()
    running = 0
    peak = 0
    threads: set[str] = set()

    def slow_miss() -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
            threads.add(threading.current_thread().name)
        time.sleep(0.02)
        with lock:
            running -= 1

    monkeypatch.setattr(store_module, "spend_constant_time_miss", slow_miss)
    store = TokenStore(home=tmp_path)
    verifier = HubTokenVerifier(store)

    await asyncio.gather(*(verifier.verify_token(t) for t in UNKNOWN))

    assert threading.main_thread().name not in threads, "argon2 ran on the event loop's thread"
    assert 1 <= peak <= store_module.HASH_WORKERS, f"{peak} argon2 verifies ran at once"


async def test_an_authorized_client_is_not_starved_by_a_flood(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", ["vault:work:read"])
    verifier = PalaiaTokenVerifier(store, "default")
    assert await verifier.verify_token(created.token) is not None  # first connect

    started = time.perf_counter()
    flood = [asyncio.create_task(verifier.verify_token(t)) for t in UNKNOWN * 2]
    # The authorized request arrives after the flood, as the 41st in line.
    access = await asyncio.create_task(verifier.verify_token(created.token))
    took = time.perf_counter() - started
    await asyncio.gather(*flood)

    assert access is not None and access.client_id == created.info.id
    # Queued behind 40 argon2 verifies on a two-thread pool this takes over a
    # second; a client that already proved its token is not made to wait.
    assert took < 0.2, f"an authorized request waited {took:.3f}s behind invalid tokens"


async def test_a_revoked_token_is_refused_right_after_it_verified(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", ["vault:work:read"])
    verifier = HubTokenVerifier(store)
    assert await verifier.verify_token(created.token) is not None

    store.revoke(created.info.id)

    assert await verifier.verify_token(created.token) is None


async def test_a_token_revoked_by_another_process_is_refused(tmp_path: Path) -> None:
    hub = TokenStore(home=tmp_path)
    created = hub.create("client", "default", ["vault:work:read"])
    verifier = HubTokenVerifier(hub)
    assert await verifier.verify_token(created.token) is not None

    # `palaia token revoke` writes the same file from another process.
    TokenStore(home=tmp_path).revoke(created.info.id)

    assert await verifier.verify_token(created.token) is None


async def test_a_wrong_secret_for_a_verified_id_is_still_refused(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", ["vault:work:read"])
    verifier = HubTokenVerifier(store)
    assert await verifier.verify_token(created.token) is not None
    token_id = created.token.removeprefix("plt_").split(".", 1)[0]

    assert await verifier.verify_token(f"plt_{token_id}.{'w' * 32}") is None
