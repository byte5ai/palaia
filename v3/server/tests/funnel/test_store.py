"""Unit coverage for :mod:`palaia_hub.funnel` (SPEC-504 deliverable #3)."""

from __future__ import annotations

from pathlib import Path

from palaia_hub.funnel import FunnelStore, format_duration


def test_a_fresh_home_has_nothing_recorded(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)

    status = store.status()

    assert status.hub_started_at is None
    assert status.vault_created_at is None
    assert status.client_connected_at is None
    assert status.first_memory_at is None
    assert status.time_to_first_memory_seconds is None
    assert status.time_to_first_memory_display is None
    assert not store.path.exists(), "a read must never create the file itself"


def test_recording_a_step_persists_it(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)

    store.record_vault_created(100.0)

    assert store.path.exists()
    assert store.status().vault_created_at == 100.0

    # A second FunnelStore over the same home reads back the same value —
    # this is what makes the timestamp survive a hub restart.
    reopened = FunnelStore(tmp_path)
    assert reopened.status().vault_created_at == 100.0


def test_each_step_is_first_write_wins(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)

    store.record_hub_started(100.0)
    store.record_hub_started(999.0)  # a later restart must not reset the start line

    assert store.status().hub_started_at == 100.0


def test_time_to_first_memory_is_none_until_both_ends_exist(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)
    store.record_hub_started(100.0)

    assert store.status().time_to_first_memory_seconds is None

    store.record_first_memory(352.0)

    status = store.status()
    assert status.time_to_first_memory_seconds == 252.0
    assert status.time_to_first_memory_display == "4m12s"


def test_time_to_first_memory_never_goes_negative(tmp_path: Path) -> None:
    """Defensive: two events published out of wall-clock order (e.g. two
    processes with slightly skewed clocks, or a test that stubs `time.time`
    non-monotonically) must never report a negative "time to first memory"
    a dashboard tile would render as nonsense."""
    store = FunnelStore(tmp_path)
    store.record_hub_started(500.0)
    store.record_first_memory(100.0)

    assert store.status().time_to_first_memory_seconds == 0.0


def test_records_default_to_now_when_no_timestamp_given(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)

    store.record_vault_created()

    assert store.status().vault_created_at is not None
    assert store.status().vault_created_at > 0


def test_all_four_steps_recorded_independently(tmp_path: Path) -> None:
    store = FunnelStore(tmp_path)
    store.record_hub_started(1.0)
    store.record_vault_created(2.0)
    store.record_client_connected(3.0)
    store.record_first_memory(4.0)

    status = store.status()
    assert status.hub_started_at == 1.0
    assert status.vault_created_at == 2.0
    assert status.client_connected_at == 3.0
    assert status.first_memory_at == 4.0


def test_format_duration_under_a_minute() -> None:
    assert format_duration(0) == "0s"
    assert format_duration(37) == "37s"
    assert format_duration(59.6) == "1m00s"  # rounds up into the next unit


def test_format_duration_minutes() -> None:
    assert format_duration(252) == "4m12s"
    assert format_duration(60) == "1m00s"


def test_format_duration_hours() -> None:
    assert format_duration(3723) == "1h02m"


def test_format_duration_never_negative() -> None:
    assert format_duration(-5) == "0s"
