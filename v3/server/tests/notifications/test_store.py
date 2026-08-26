"""SPEC-307 deliverable #1's notification center: durable, capped, read state."""

from __future__ import annotations

from pathlib import Path

from palaia_hub.notifications.store import MAX_NOTIFICATIONS, NotificationStore


def test_create_and_list_newest_first(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "n.sqlite3")
    store.create(title="first")
    store.create(title="second")

    listed = store.list()
    assert [n.title for n in listed] == ["second", "first"]
    assert all(n.read is False for n in listed)


def test_mark_read_and_unread_count(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "n.sqlite3")
    a = store.create(title="a")
    store.create(title="b")

    assert store.unread_count() == 2
    read = store.mark_read(a.id)
    assert read is not None
    assert read.read is True
    assert store.unread_count() == 1
    assert [n.title for n in store.list(unread_only=True)] == ["b"]


def test_mark_read_unknown_id_returns_none(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "n.sqlite3")
    assert store.mark_read(9999) is None


def test_mark_all_read(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "n.sqlite3")
    store.create(title="a")
    store.create(title="b")

    store.mark_all_read()

    assert store.unread_count() == 0


def test_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "n.sqlite3"
    store = NotificationStore(path)
    store.create(title="persisted")
    store.close()

    reopened = NotificationStore(path)
    assert [n.title for n in reopened.list()] == ["persisted"]


def test_is_capped_at_max_notifications(tmp_path: Path) -> None:
    store = NotificationStore(tmp_path / "n.sqlite3")
    for i in range(MAX_NOTIFICATIONS + 10):
        store.create(title=f"n{i}")

    listed = store.list(limit=MAX_NOTIFICATIONS + 50)
    assert len(listed) == MAX_NOTIFICATIONS
    # The oldest were trimmed, the newest kept.
    assert listed[-1].title == "n10"
    assert listed[0].title == f"n{MAX_NOTIFICATIONS + 9}"
