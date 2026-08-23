from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.hooks.store import HookError, HookStore


def test_create_returns_secret_once_and_list_info_never_includes_it(tmp_path: Path) -> None:
    store = HookStore(tmp_path)

    created = store.create("https://example.com/hook", ["memory.entry.created"])

    assert created.secret
    assert created.info.url == "https://example.com/hook"
    assert created.info.events == ["memory.entry.created"]
    assert created.info.enabled is True

    listed = store.list_info()
    assert len(listed) == 1
    assert not hasattr(listed[0], "secret")


def test_create_rejects_a_non_http_url(tmp_path: Path) -> None:
    store = HookStore(tmp_path)

    with pytest.raises(HookError):
        store.create("not-a-url")


def test_default_events_filter_is_wildcard(tmp_path: Path) -> None:
    store = HookStore(tmp_path)

    created = store.create("https://example.com/hook")

    assert created.info.events == ["*"]


def test_set_enabled_and_delete_round_trip(tmp_path: Path) -> None:
    store = HookStore(tmp_path)
    created = store.create("https://example.com/hook")

    disabled = store.set_enabled(created.info.id, False)
    assert disabled.enabled is False

    store.delete(created.info.id)
    assert store.get(created.info.id) is None


def test_delete_unknown_hook_raises(tmp_path: Path) -> None:
    store = HookStore(tmp_path)

    with pytest.raises(HookError):
        store.delete("no-such-id")


def test_store_persists_across_instances(tmp_path: Path) -> None:
    store = HookStore(tmp_path)
    created = store.create("https://example.com/hook", ["inbox.captured"])

    reloaded = HookStore(tmp_path)
    record = reloaded.get(created.info.id)

    assert record is not None
    assert record.url == "https://example.com/hook"
    assert record.secret == created.secret
    assert record.events == ["inbox.captured"]


