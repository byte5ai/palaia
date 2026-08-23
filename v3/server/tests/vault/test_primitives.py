"""Atomic writes, frontmatter, permalinks and wikilinks — the raw primitives."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from palaia_hub.vault import frontmatter as fm
from palaia_hub.vault import links
from palaia_hub.vault import permalink as pl
from palaia_hub.vault.atomic import (
    TEMP_SUFFIX,
    atomic_write_text,
    sha256_bytes,
    sweep_temp_files,
)

# --------------------------------------------------------------------- atomic


def test_atomic_write_creates_parents_and_content(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "note.md"
    data = atomic_write_text(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"
    assert sha256_bytes(data) == sha256_bytes(target.read_bytes())


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "note.md"
    atomic_write_text(target, "one\n")
    atomic_write_text(target, "two\n")
    assert list(tmp_path.glob(f"*{TEMP_SUFFIX}")) == []
    assert target.read_text(encoding="utf-8") == "two\n"


def test_atomic_write_fsyncs_file_and_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    atomic_write_text(tmp_path / "note.md", "durable\n")
    # One fsync for the file's bytes, one for the directory entry.
    assert len(calls) >= 2


def test_atomic_write_cleans_up_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        atomic_write_text(tmp_path / "note.md", "x")
    assert list(tmp_path.glob(f"*{TEMP_SUFFIX}")) == []


def test_sweep_temp_files_removes_crash_residue(tmp_path: Path) -> None:
    orphan = tmp_path / f".note.md.abc{TEMP_SUFFIX}"
    orphan.write_text("half written", encoding="utf-8")
    removed = sweep_temp_files(tmp_path)
    assert [path.name for path in removed] == [orphan.name]
    assert not orphan.exists()


# ---------------------------------------------------------------- frontmatter


def test_parse_plain_note_without_fence_is_not_malformed() -> None:
    parsed = fm.parse("Just a note.\n")
    assert parsed.frontmatter == {}
    assert parsed.has_fence is False
    assert parsed.malformed is False
    assert parsed.body == "Just a note.\n"


def test_parse_unclosed_fence_is_malformed() -> None:
    parsed = fm.parse("---\ntitle: Broken\n\nbody\n")
    assert parsed.malformed is True
    assert parsed.has_fence is True


def test_parse_invalid_yaml_is_malformed() -> None:
    parsed = fm.parse("---\ntitle: [unclosed\n---\n\nbody\n")
    assert parsed.malformed is True
    assert parsed.frontmatter == {}


def test_parse_handles_bom_and_crlf() -> None:
    parsed = fm.parse("﻿---\r\ntitle: CRLF\r\n---\r\n\r\nbody\r\n")
    assert parsed.frontmatter["title"] == "CRLF"
    assert parsed.body == "body\n"


def test_parse_preserves_unknown_keys() -> None:
    parsed = fm.parse("---\ntitle: T\ncustom_key: kept\n---\n\nbody\n")
    assert parsed.frontmatter["custom_key"] == "kept"


def test_string_value_coerces_list_and_scalars() -> None:
    assert fm.string_value({"title": ["First", "Second"]}, "title") == ("First", True)
    assert fm.string_value({"title": "A, B"}, "title") == ("A, B", False)
    assert fm.string_value({"title": 42}, "title") == ("42", True)


def test_string_list_normalizes_comma_strings_and_natives() -> None:
    assert fm.string_list("infra, docs") == ["infra", "docs"]
    assert fm.string_list(["a", 2, True]) == ["a", "2", "true"]
    assert fm.string_list(None) == []


def test_render_uses_canonical_key_order_and_single_blank_line() -> None:
    text = fm.render(
        {"zeta": 1, "permalink": "notes/x", "title": "X", "alpha": 2, "type": "note"},
        "body\n",
    )
    lines = text.split("\n")
    assert lines[0] == "---"
    assert lines[1:4] == ["title: X", "permalink: notes/x", "type: note"]
    assert lines[4:6] == ["alpha: 2", "zeta: 1"]  # unknown keys, alphabetical
    assert lines[6] == "---"
    assert lines[7] == ""
    assert lines[8] == "body"


def test_render_round_trips_through_parse() -> None:
    original = {"title": "Round", "permalink": "notes/round", "tags": ["a", "b"]}
    parsed = fm.parse(fm.render(original, "text\n"))
    assert parsed.frontmatter == original
    assert parsed.body == "text\n"


# ------------------------------------------------------------------ permalinks


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("API Gateway", "api-gateway"),
        ("  Spaced   Out  ", "spaced-out"),
        ("Über Größe", "ueber-groesse"),
        ("Route 66", "route-66"),
        ("!!!", ""),
    ],
)
def test_slugify(title: str, expected: str) -> None:
    assert pl.slugify(title) == expected


def test_mint_mirrors_the_folder_path() -> None:
    assert pl.mint("projects/api/API Gateway.md", "API Gateway") == "projects/api/api-gateway"
    assert pl.mint("Note.md", "") == "note"


def test_make_unique_appends_suffixes() -> None:
    assert pl.make_unique("notes/x", set()) == "notes/x"
    assert pl.make_unique("notes/x", {"notes/x"}) == "notes/x-2"
    assert pl.make_unique("notes/x", {"notes/x", "notes/x-2"}) == "notes/x-3"


@pytest.mark.parametrize(
    ("value", "volatile"),
    [
        ("Preise Stand 2026-08-22", True),
        ("Preise Stand 2026-08", True),
        ("Migration v2.3", True),
        ("OpenClaw 2026.5.7", True),
        ("releases/2026-08-22", True),
        ("Route 66", False),
        ("API Gateway", False),
        ("api-gateway-v2", False),
    ],
)
def test_volatility_patterns(value: str, volatile: bool) -> None:
    assert bool(pl.volatility_violations(value)) is volatile


def test_is_canonical() -> None:
    assert pl.is_canonical("projects/api-gateway")
    assert not pl.is_canonical("Projects/API_Gateway")
    assert not pl.is_canonical("/leading")
    assert not pl.is_canonical("trailing/")


# ----------------------------------------------------------------- wikilinks


LINK_SAMPLE = """\
Prose about [[API Gateway]] and [[API Gateway|the gateway]].

- part_of [[ACME Platform]]
- [rate] 100 req/min ^rate

![[Pricing#^base-rate]]

Inline `[[Not A Link]]` stays code.

```markdown
[[API Gateway]] inside a fence stays code.
```
"""


def test_iter_links_finds_targets_anchors_and_display() -> None:
    found = list(links.iter_links(LINK_SAMPLE))
    targets = [(link.target, link.anchor, link.display, link.embed) for link in found]
    assert ("API Gateway", None, None, False) in targets
    assert ("API Gateway", None, "the gateway", False) in targets
    assert ("ACME Platform", None, None, False) in targets
    assert ("Pricing", "^base-rate", None, True) in targets
    assert all(link.target != "Not A Link" for link in found)


def test_iter_links_skips_fenced_code() -> None:
    fenced = [link for link in links.iter_links(LINK_SAMPLE) if link.line >= 13]
    assert fenced == []


def test_rewrite_targets_preserves_anchor_and_display() -> None:
    text = "[[API Gateway|gw]] and ![[API Gateway#^rate]] and [[Other]]\n"
    rewritten, count = links.rewrite_targets(
        text, lambda target: "Edge Gateway" if target == "API Gateway" else None
    )
    assert count == 2
    assert rewritten == "[[Edge Gateway|gw]] and ![[Edge Gateway#^rate]] and [[Other]]\n"


def test_rewrite_targets_leaves_code_alone() -> None:
    rewritten, count = links.rewrite_targets(
        LINK_SAMPLE, lambda target: "Edge Gateway" if target == "API Gateway" else None
    )
    assert count == 2
    assert "[[API Gateway]] inside a fence stays code." in rewritten
    assert "`[[Not A Link]]`" in rewritten
