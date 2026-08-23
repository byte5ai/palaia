"""Naming/composition rules — in particular the SPEC-002 FINDINGS Q4 foot-gun:

``FastMCP.mount(server, namespace=ns, tool_names={old: new})`` renames
*before* adding the namespace prefix, so passing an already-namespaced
value as the rename double-prefixes it. These tests pin down
``compose_tool_name``/``decompose_final_name``/``resolve_tool_names``
against that exact scenario.
"""

from __future__ import annotations

import logging

from palaia_hub.gateway.naming import (
    compose_tool_name,
    decompose_final_name,
    resolve_tool_names,
    sanitize_tool_name,
)


def test_sanitize_replaces_invalid_chars_and_reports_change() -> None:
    result = sanitize_tool_name("find notes!")
    assert result.value == "find_notes"
    assert result.changed is True
    assert result.original == "find notes!"


def test_sanitize_leaves_valid_names_untouched() -> None:
    result = sanitize_tool_name("quick_search")
    assert result.value == "quick_search"
    assert result.changed is False


def test_sanitize_prefixes_a_leading_digit() -> None:
    result = sanitize_tool_name("2fast")
    assert result.value == "t_2fast"
    assert result.changed is True


def test_sanitize_empty_result_falls_back_to_tool() -> None:
    result = sanitize_tool_name("!!!")
    assert result.value == "tool"
    assert result.changed is True


def test_compose_tool_name_matches_mount_behavior() -> None:
    # This is exactly what FastMCP's mount() produces for
    # mount(server, namespace="remote", tool_names={"echo": "say"}):
    # remote_say, not remote_echo and not the double-prefixed remote_remote_say.
    assert compose_tool_name("remote", "say") == "remote_say"


def test_compose_tool_name_empty_namespace_is_passthrough() -> None:
    assert compose_tool_name("", "say") == "say"


def test_decompose_final_name_inverts_compose() -> None:
    assert decompose_final_name("work_memory", "work_memory_search") == "search"


def test_decompose_final_name_warns_when_prefix_missing(
    caplog: logging.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="palaia_hub.gateway.naming")
    result = decompose_final_name("work_memory", "totally_custom_name")
    assert result == "totally_custom_name"
    assert any("double-prefix" in record.message for record in caplog.records)


def test_reproduces_the_findings_q4_double_prefix_bug_when_done_wrong() -> None:
    # The spike's first (buggy) attempt: pass the *already-composed* display
    # name straight into tool_names. compose_tool_name shows what actually
    # comes out the other end of mount() when you do that.
    wrong_pre_namespace_value = "remote_say"  # what the buggy code passed
    assert compose_tool_name("remote", wrong_pre_namespace_value) == "remote_remote_say"

    # The fix: pass the pre-namespace value.
    right_pre_namespace_value = "say"
    assert compose_tool_name("remote", right_pre_namespace_value) == "remote_say"


def test_resolve_tool_names_sanitizes_and_warns(
    caplog: logging.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="palaia_hub.gateway.naming")
    resolved = resolve_tool_names("work_memory", {"search": "quick search!"})
    assert resolved == {"search": "quick_search"}
    assert any("sanitized to" in record.message for record in caplog.records)


def test_resolve_tool_names_drops_noop_renames() -> None:
    resolved = resolve_tool_names("work_memory", {"search": "search"})
    assert resolved == {}


def test_resolve_tool_names_empty_input() -> None:
    assert resolve_tool_names("work_memory", None) == {}
    assert resolve_tool_names("work_memory", {}) == {}


def test_resolve_tool_names_composes_to_the_expected_final_name() -> None:
    resolved = resolve_tool_names("work_memory", {"search": "find"})
    final_name = compose_tool_name("work_memory", resolved["search"])
    assert final_name == "work_memory_find"
