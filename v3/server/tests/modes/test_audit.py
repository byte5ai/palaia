from __future__ import annotations

from pathlib import Path

from palaia_hub.modes.audit import ModeAuditLog


def test_recording_an_entry_creates_the_file(tmp_path: Path) -> None:
    log = ModeAuditLog(tmp_path)

    log.record(from_mode="locked", to_mode="cloud", accepted=True, changed_keys=("mode",))

    assert log.path.exists()
    entries = log.recent()
    assert len(entries) == 1
    assert entries[0]["from_mode"] == "locked"
    assert entries[0]["to_mode"] == "cloud"
    assert entries[0]["accepted"] is True
    assert entries[0]["changed_keys"] == ["mode"]


def test_a_refused_attempt_is_recorded_too(tmp_path: Path) -> None:
    log = ModeAuditLog(tmp_path)

    log.record(
        from_mode="locked",
        to_mode="cloud",
        accepted=False,
        reason="mode 'cloud' requires an authentication method",
        changed_keys=("mode", "auth_enabled"),
    )

    entries = log.recent()
    assert entries[0]["accepted"] is False
    assert "authentication method" in entries[0]["reason"]


def test_recent_returns_newest_first_and_respects_limit(tmp_path: Path) -> None:
    log = ModeAuditLog(tmp_path)
    for i in range(5):
        log.record(from_mode="locked", to_mode=f"mode-{i}", accepted=True)

    entries = log.recent(limit=2)

    assert [e["to_mode"] for e in entries] == ["mode-4", "mode-3"]


def test_recent_on_a_fresh_home_with_no_log_is_empty(tmp_path: Path) -> None:
    log = ModeAuditLog(tmp_path)

    assert log.recent() == []


def test_each_entry_gets_a_unique_id_and_timestamp(tmp_path: Path) -> None:
    log = ModeAuditLog(tmp_path)

    first = log.record(from_mode="locked", to_mode="cloud", accepted=True)
    second = log.record(from_mode="cloud", to_mode="open", accepted=True)

    assert first.id != second.id
    assert first.ts > 0
