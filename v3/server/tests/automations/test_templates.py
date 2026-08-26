"""SPEC-307 deliverable #3: templating."""

from __future__ import annotations

import logging

import pytest

from palaia_hub.automations.templates import render
from palaia_hub.events.schema import Envelope


def _envelope(**overrides: object) -> Envelope:
    defaults: dict[str, object] = {
        "event": "memory.entry.created",
        "data": {"path": "work/x.md", "severity": "high"},
        "origin": "vault",
        "vault": "work",
    }
    defaults.update(overrides)
    return Envelope(**defaults)  # type: ignore[arg-type]


def test_substitutes_event_vault_and_data_fields() -> None:
    template = "{{event}} in {{vault}}: {{data.path}} is {{data.severity}}"
    result = render(template, _envelope())
    assert result == "memory.entry.created in work: work/x.md is high"


def test_missing_key_renders_empty_and_never_raises() -> None:
    result = render("severity: {{data.missing}}", _envelope())
    assert result == "severity: "


def test_missing_key_logs_once_per_render_call(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        render("{{data.a}} {{data.a}} {{data.b}}", _envelope())
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_template_with_no_placeholders_passes_through_unchanged() -> None:
    assert render("a fixed literal string", _envelope()) == "a fixed literal string"


def test_permalink_placeholder() -> None:
    envelope = _envelope(permalink="projects/x")
    assert render("{{permalink}}", envelope) == "projects/x"
