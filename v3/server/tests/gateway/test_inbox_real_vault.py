"""SPEC-107 integration test: a capture note composed by
:mod:`palaia_hub.gateway.inbox` and written through the *real* vault engine
(SPEC-102) is a format-spec-valid ``inbox/`` note (``v3/docs/vault-format.md``
§7) — mandatory ``[entity]``/``[why]`` bullets present, deterministic
``capture_id``, ``status: uncurated``, canonical frontmatter/body shape.

Deliberately independent of the gateway's ``VaultService`` abstraction: this
proves the note *shape* the gateway package composes (with zero
``palaia_hub.vault`` import there) survives a real engine round-trip,
without building the full production adapter that wiring a real vault into
the gateway would need (that adapter is SPEC-113's scope).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from palaia_hub.gateway import inbox as inbox_shape
from palaia_hub.vault import VaultEngine

pytestmark = pytest.mark.anyio

_CAPTURE_ID_RE = re.compile(r"^cap-[0-9a-f]{10}$")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _open_engine(tmp_path: Path) -> VaultEngine:
    engine = VaultEngine(tmp_path / "vault", "work")
    await engine.open(purpose="integration test vault")
    return engine


async def _write_capture(
    engine: VaultEngine,
    *,
    what_it_concerns: str,
    why_keep: str,
    content: str,
    source: str | None = None,
) -> tuple[str, str, str]:
    """Compose and write one capture the way a real ``VaultService.capture``
    adapter would: mint the permalink under ``inbox/`` via ``write_note``
    (letting the engine own permalink minting/uniqueness), then patch in the
    capture-specific frontmatter this SPEC's gateway layer defines.

    Returns ``(permalink, path, capture_id)``. ``path`` is the vault-relative
    file path (which may differ from the permalink — a real capture adapter
    would pass its own slugified path; here the engine's `write_note` mints
    the note file at ``inbox/<what_it_concerns>.md`` and mints its *own*
    slugified permalink from the title, per format spec §3.1).
    """
    resolved_source = (source or "").strip() or inbox_shape.default_source()
    content_hash = inbox_shape.content_hash_for(what_it_concerns, why_keep, content)
    body = inbox_shape.compose_capture_body(
        what_it_concerns=what_it_concerns,
        why_keep=why_keep,
        content=content,
        source=resolved_source,
        content_hash=content_hash,
    )
    result = await engine.write_note(
        f"inbox/{what_it_concerns}",
        body=body,
        title=what_it_concerns,
        frontmatter={"type": "capture", "tags": ["inbox"], "status": "uncurated"},
    )
    assert result.note is not None
    permalink = result.note.permalink
    path = result.note.path
    assert permalink is not None
    capture_id = inbox_shape.capture_id_for(permalink)
    # capture_id depends on the final (post-uniquing) permalink, so it is a
    # second write — the same "engine mints identity, capture stamps
    # capture_id" two-step a real capture() adapter would perform.
    await engine.edit_note(
        permalink,
        expected_checksum=result.note.checksum,
        frontmatter={"capture_id": capture_id},
    )
    return permalink, path, capture_id


async def test_capture_with_only_mandatory_fields_is_format_valid(tmp_path: Path) -> None:
    engine = await _open_engine(tmp_path)
    permalink, path, capture_id = await _write_capture(
        engine,
        what_it_concerns="API Gateway",
        why_keep="The rate limit was chosen deliberately; future work will trip over it.",
        content="We capped ingest at 100 req/min because the embed queue saturates above that.",
    )

    note = await engine.read_note(permalink)

    # Frontmatter shape (format spec §2.1/§7).
    assert note.frontmatter["type"] == "capture"
    assert note.frontmatter["status"] == "uncurated"
    assert note.frontmatter["tags"] == ["inbox"]
    assert note.frontmatter["capture_id"] == capture_id
    assert _CAPTURE_ID_RE.match(note.frontmatter["capture_id"])
    assert note.permalink is not None
    assert note.permalink.startswith("inbox/")
    assert not note.malformed_frontmatter

    # Mandatory body bullets (§7): entity and why must both be present.
    assert "- [entity] API Gateway" in note.body
    assert "- [why] The rate limit was chosen deliberately" in note.body

    # File itself is on disk, LF-only, one blank line after the closing fence
    # — the canonical write form (§2.2), for free from `fm.render`/`write_note`.
    raw = (engine.root / path).read_text(encoding="utf-8")
    assert "\r" not in raw
    assert raw.startswith("---\n")

    # It is a real, git-committed write (SPEC-102 write-through guarantee).
    assert engine.git.head() is not None


async def test_capture_id_is_deterministic_from_the_permalink(tmp_path: Path) -> None:
    engine = await _open_engine(tmp_path)
    permalink, _path, capture_id = await _write_capture(
        engine,
        what_it_concerns="Deterministic ID Check",
        why_keep="Proves capture_id is a pure function of the permalink.",
        content="Nothing interesting; just a fixture.",
    )
    assert capture_id == inbox_shape.capture_id_for(permalink)


async def test_capture_note_is_immediately_readable_and_listed_in_inbox(tmp_path: Path) -> None:
    engine = await _open_engine(tmp_path)
    permalink, _path, _capture_id = await _write_capture(
        engine,
        what_it_concerns="Immediately Searchable",
        why_keep="Uncurated captures must be visible right away (§7).",
        content="No curation step should be required to find this.",
    )

    entries = await engine.list_dir("inbox")
    assert any(entry.permalink == permalink for entry in entries)


async def test_source_defaults_when_omitted_and_is_honored_when_given(tmp_path: Path) -> None:
    engine = await _open_engine(tmp_path)
    permalink, _path, _capture_id = await _write_capture(
        engine,
        what_it_concerns="Default Source",
        why_keep="Source should default to something plausible.",
        content="content body",
    )
    note = await engine.read_note(permalink)
    assert "- [source] agent capture, " in note.body

    permalink2, _path2, _capture_id2 = await _write_capture(
        engine,
        what_it_concerns="Explicit Source",
        why_keep="Source should be honored when the caller supplies one.",
        content="content body",
        source="PR #88 review, cwendler, 2026-08-22",
    )
    note2 = await engine.read_note(permalink2)
    assert "- [source] PR #88 review, cwendler, 2026-08-22" in note2.body


async def test_two_distinct_captures_get_distinct_permalinks_and_capture_ids(
    tmp_path: Path,
) -> None:
    engine = await _open_engine(tmp_path)
    permalink_a, _path_a, capture_id_a = await _write_capture(
        engine, what_it_concerns="Thing A", why_keep="why A", content="content A"
    )
    permalink_b, _path_b, capture_id_b = await _write_capture(
        engine, what_it_concerns="Thing B", why_keep="why B", content="content B"
    )
    assert permalink_a != permalink_b
    assert capture_id_a != capture_id_b
