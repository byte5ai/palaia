from __future__ import annotations

from palaia_hub.config import HubConfig
from palaia_hub.modes.hardening import build_checklist
from palaia_hub.modes.selftest import SelfTestResult


def _item(items: list, item_id: str):  # type: ignore[no-untyped-def]
    return next(i for i in items if i.id == item_id)


def test_auth_mandatory_item_is_auto_verified_true_when_auth_enabled() -> None:
    config = HubConfig(mode="open", auth_enabled=True)
    checklist = build_checklist(config, rate_limiting_active=True)

    item = _item(checklist, "auth_mandatory")
    assert item.auto is True
    assert item.passed is True


def test_rate_limited_item_reflects_what_the_caller_actually_observed() -> None:
    checklist = build_checklist(HubConfig(mode="open"), rate_limiting_active=False)

    item = _item(checklist, "rate_limited")
    assert item.auto is True
    assert item.passed is False


def test_tls_item_is_manual_when_no_self_test_has_run_yet() -> None:
    checklist = build_checklist(HubConfig(mode="open"), rate_limiting_active=True)

    item = _item(checklist, "tls")
    assert item.auto is False
    assert item.passed is None
    assert "not checked yet" in item.detail


def test_tls_item_is_auto_verified_after_a_successful_self_test() -> None:
    self_test = SelfTestResult(
        checked_url="https://hub.example.com/api/info",
        reachable=True,
        status_code=200,
        latency_ms=12.3,
        error="",
    )
    checklist = build_checklist(
        HubConfig(mode="open"), rate_limiting_active=True, last_self_test=self_test
    )

    item = _item(checklist, "tls")
    assert item.auto is True
    assert item.passed is True


def test_tls_item_is_auto_but_failed_after_an_unreachable_self_test() -> None:
    self_test = SelfTestResult(
        checked_url="https://hub.example.com/api/info",
        reachable=False,
        status_code=None,
        latency_ms=None,
        error="could not connect",
    )
    checklist = build_checklist(
        HubConfig(mode="open"), rate_limiting_active=True, last_self_test=self_test
    )

    item = _item(checklist, "tls")
    assert item.auto is True
    assert item.passed is False
    assert "could not connect" in item.detail


def test_owner_account_item_is_manual_when_the_caller_cannot_check() -> None:
    checklist = build_checklist(HubConfig(mode="open"), rate_limiting_active=True)

    item = _item(checklist, "owner_account")
    assert item.auto is False
    assert item.passed is None


def test_owner_account_item_is_auto_when_the_caller_checked() -> None:
    checklist = build_checklist(
        HubConfig(mode="open"), rate_limiting_active=True, owner_account_configured=True
    )

    item = _item(checklist, "owner_account")
    assert item.auto is True
    assert item.passed is True


def test_dashboard_exposure_acknowledgement_is_always_manual() -> None:
    checklist = build_checklist(HubConfig(mode="open"), rate_limiting_active=True)

    item = _item(checklist, "dashboard_exposure_acknowledged")
    assert item.auto is False
    assert item.passed is None
