"""Unit tests for the pure composition helpers in
:mod:`palaia_hub.gateway.inbox` (capture_id derivation, dedup hashing,
missing-field messaging) — independent of any ``VaultService`` backend.
"""

from __future__ import annotations

import hashlib

from palaia_hub.gateway import inbox


def test_capture_id_matches_the_format_spec_formula() -> None:
    permalink = "inbox/api-gateway"
    expected = "cap-" + hashlib.sha256(permalink.encode("utf-8")).hexdigest()[:10]
    assert inbox.capture_id_for(permalink) == expected


def test_capture_id_is_deterministic_and_permalink_specific() -> None:
    a = inbox.capture_id_for("inbox/foo")
    b = inbox.capture_id_for("inbox/foo")
    c = inbox.capture_id_for("inbox/bar")
    assert a == b
    assert a != c


def test_content_hash_is_stable_under_case_and_whitespace_reformatting() -> None:
    h1 = inbox.content_hash_for("API Gateway", "why it matters", "the raw detail")
    h2 = inbox.content_hash_for("  api gateway  ", "WHY IT MATTERS", "the raw detail")
    assert h1 == h2


def test_content_hash_differs_for_different_content() -> None:
    h1 = inbox.content_hash_for("A", "why", "content")
    h2 = inbox.content_hash_for("B", "why", "content")
    assert h1 != h2


def test_missing_capture_fields_detects_blank_and_absent_values() -> None:
    missing = inbox.missing_capture_fields(what_it_concerns="x", why_keep="   ", content=None)
    assert missing == ["why_keep", "content"]


def test_missing_capture_fields_empty_when_all_present() -> None:
    assert inbox.missing_capture_fields(what_it_concerns="x", why_keep="y", content="z") == []


def test_missing_fields_message_names_the_field_and_gives_an_example() -> None:
    message = inbox.missing_fields_message(["why_keep"])
    assert "why_keep" in message
    assert "Example:" in message


def test_compose_and_extract_capture_hash_round_trip() -> None:
    content_hash = inbox.content_hash_for("A", "why", "content")
    body = inbox.compose_capture_body(
        what_it_concerns="A",
        why_keep="why",
        content="content",
        source="src",
        content_hash=content_hash,
    )
    assert inbox.extract_capture_hash(body) == content_hash
    assert "- [entity] A" in body
    assert "- [why] why" in body
    assert "- [raw] content" in body
    assert "- [source] src" in body


def test_extract_capture_hash_returns_none_when_absent() -> None:
    assert inbox.extract_capture_hash("no hash bullet here") is None


def test_default_source_names_a_date() -> None:
    source = inbox.default_source()
    assert source.startswith("agent capture, ")


def test_capture_frontmatter_matches_format_spec_section_7() -> None:
    fm = inbox.capture_frontmatter(capture_id="cap-0123456789")
    assert fm == {
        "type": "capture",
        "tags": ["inbox"],
        "status": "uncurated",
        "capture_id": "cap-0123456789",
    }
