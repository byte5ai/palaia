from __future__ import annotations

from palaia_addon_sdk.jargon import find_jargon


def test_tool_names_and_code_are_not_jargon() -> None:
    assert find_jargon("Call `work_memory_capture` when something matters.") == []
    assert find_jargon("| `personal_memory_recall` | recall from it |") == []
    assert find_jargon("```\nmcp add palaia\n```\n") == []


def test_jargon_word_is_reported() -> None:
    assert find_jargon("The curator files it into the vault later.") == ["vault", "curator"]


def test_no_jargon_in_plain_sentence() -> None:
    assert find_jargon("Fetch and convert web pages to text for an agent to read.") == []
