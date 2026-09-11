"""Issue #397: marketplace edge cases the rc1 review found by reading."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from palaia_hub.market.install import (
    ConsentStore,
    InstallService,
    MarketInstallError,
    _upstream_config,
)
from palaia_hub.market.service import _market_entry_from_registry
from palaia_hub.registry.models import RegistryServer


def test_a_registry_entry_with_a_null_repository_still_maps() -> None:
    server = RegistryServer(
        id="x",
        name="io.example/x",
        description="d",
        version=None,
        raw={"server": {"repository": None, "remotes": [{"url": "https://x.example/mcp"}]}},
    )
    entry = _market_entry_from_registry(server)
    assert entry.maintainer == "unknown"


def test_consent_tokens_are_pruned_once_expired_or_used() -> None:
    store = ConsentStore(ttl_seconds=0.01)
    stale, _ = store.issue("acme.one")
    time.sleep(0.02)
    fresh, _ = store.issue("acme.two")
    assert stale not in store._tokens, "an expired token is dropped on the next issue"
    assert fresh in store._tokens
    store.consume(fresh, "acme.two")
    store.issue("acme.three")
    assert fresh not in store._tokens, "a used token is dropped too"


def test_an_unusable_config_field_name_is_an_install_error_not_a_500() -> None:
    with pytest.raises(MarketInstallError, match="environment variable"):
        _upstream_config(
            key="k",
            kind="stdio",
            display_name="x",
            command="c",
            args=[],
            env={},
            env_secrets={"API-KEY": "secret-name"},
        )


@pytest.mark.anyio
async def test_update_available_fires_when_it_turns_on_not_on_every_check() -> None:
    published: list[tuple[str, dict[str, Any]]] = []
    outs = [
        SimpleNamespace(
            entry_id="acme.tool",
            upstream_key="acme-tool",
            installed_ref="1.0.0",
            current_ref="1.1.0",
            update_available=True,
        )
    ]

    async def _outs() -> list[Any]:
        return list(outs)

    fake = SimpleNamespace(
        _outs=_outs,
        _publish=lambda name, data: published.append((name, data)),
        _update_announced=set(),
    )
    check = InstallService.check_updates

    assert len(await check(fake)) == 1  # type: ignore[arg-type]
    assert len(await check(fake)) == 1  # type: ignore[arg-type]
    assert [name for name, _ in published] == ["addon.update_available"]

    outs[0].update_available = False
    assert await check(fake) == []  # type: ignore[arg-type]
    outs[0].update_available = True
    assert len(await check(fake)) == 1  # type: ignore[arg-type]
    assert [name for name, _ in published] == ["addon.update_available"] * 2
