"""Read a palaia v2 ``.palaia/`` store and map its entries to v3 notes.

**Clean-room, format-only.** This module never imports ``palaia`` (the v2
package at the repository root) — the hard track-separation rule
(``AGENTS.md``) forbids it regardless of license. It re-implements just
enough of the v2 on-disk entry format (``palaia/entry.py``,
``palaia/frontmatter.py``, ``palaia/store.py`` in the v2 tree, read only as
a format reference) to read entries back: a ``---``-fenced frontmatter block
of simple ``key: value`` pairs followed by a body, one file per entry under
``hot/``, ``warm/`` or ``cold/``.

v2 stores may use either backend (``StorageBackend`` in v2's
``palaia/backends/protocol.py``) for its metadata index/embedding cache —
but entry *content* always lives in these per-tier files regardless of
backend, so reading the tier directories covers both cases; nothing here
touches the v2 SQLite/Postgres backend files at all.

Mapping (format spec §11, "palaia v2 import"):

- v2 ``type: memory`` → v3 ``type: note``
- v2 ``type: process`` → v3 ``type: process``
- v2 ``type: task`` → dropped into ``inbox/`` as a v3 ``capture`` for the
  curator to file (v2 tasks have no v3 equivalent type; the inbox contract
  is the closest fit and keeps them out of ordinary recall until curated)
- any other/unknown ``type`` → v3 ``type: note`` (warn-first: an unexpected
  legacy type is imported, not rejected)
- v2 ``tier`` (``hot``/``warm``/``cold``) → an ``import.decay_seed`` frontmatter
  value (``hot`` → 1.0, ``warm`` → 0.5, ``cold`` → 0.1) plus the tier itself,
  both under the ``import`` provenance key (§2: unknown keys are preserved
  verbatim and indexed as searchable metadata) — SPEC-104's real decay model
  is not merged yet, so this is a documented *seed*, not a live score.
- v2 ``scope`` (``team``/``private``/``public``) → v3 ``scope``
  (``project``/``private``/``shared``) — the closest v3 equivalents per
  MASTERPLAN §5.1's three-scope model.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palaia_hub.vault import frontmatter as fm
from palaia_hub.vault import permalink as pl

from .models import MappedNote, SkippedItem

#: v2 tier directories, in the order the store creates them (palaia/store.py TIERS).
V2_TIERS: tuple[str, ...] = ("hot", "warm", "cold")

#: v2 type → v3 type (format spec §11); "task" is handled separately (inbox).
_TYPE_MAP: dict[str, str] = {"memory": "note", "process": "process"}

#: v3 type → the folder it lands in under IMPORT_FOLDER (not just "<type>s" —
#: "process" would otherwise mint "processs").
_TYPE_FOLDER: dict[str, str] = {"note": "notes", "process": "processes"}

#: v2 tier → seed decay score (documented, not SPEC-104's live model).
TIER_DECAY_SEED: dict[str, float] = {"hot": 1.0, "warm": 0.5, "cold": 0.1}

#: v2 scope → v3 scope (MASTERPLAN §5.1's three-scope model).
_SCOPE_MAP: dict[str, str] = {"team": "project", "private": "private", "public": "shared"}

IMPORT_FOLDER = "imported/v2"


@dataclass(frozen=True, slots=True)
class V2SourceEntry:
    """One raw v2 entry file, before mapping."""

    source_path: str
    tier: str
    frontmatter: dict[str, Any]
    body: str


def find_store_root(path: Path) -> Path:
    """Resolve ``path`` to the actual ``.palaia/`` store directory.

    Accepts either the store directory itself (it has ``hot``/``warm``/
    ``cold`` subdirectories) or its parent project directory (it has a
    ``.palaia`` child) — v2's own resolution order (``palaia/config.py``)
    supports both shapes of "point me at a v2 store".
    """
    if path.name == ".palaia" or any((path / tier).is_dir() for tier in V2_TIERS):
        return path
    candidate = path / ".palaia"
    if candidate.is_dir():
        return candidate
    return path


def iter_source_entries(store_root: Path) -> Iterator[V2SourceEntry]:
    """Yield every entry file under ``hot/``, ``warm/`` and ``cold/``, sorted."""
    for tier in V2_TIERS:
        tier_dir = store_root / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.glob("*.md")):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            relative = f"{tier}/{path.name}"
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                yield V2SourceEntry(
                    source_path=relative, tier=tier, frontmatter={"__undecodable__": True}, body=""
                )
                continue
            parsed = fm.parse(text)
            yield V2SourceEntry(
                source_path=relative, tier=tier, frontmatter=parsed.frontmatter, body=parsed.body
            )


def map_v2_entry(entry: V2SourceEntry) -> MappedNote | SkippedItem:
    """Map one v2 entry to a v3 :class:`MappedNote`, or explain why it can't be."""
    if entry.frontmatter.get("__undecodable__"):
        return SkippedItem(entry.source_path, "cannot decode file as UTF-8 text")

    source_id = entry.frontmatter.get("id")
    if not source_id or not isinstance(source_id, str):
        return SkippedItem(
            entry.source_path,
            "missing or non-string 'id' field in frontmatter; cannot derive a stable identity",
        )

    if not entry.body.strip():
        return SkippedItem(entry.source_path, "entry body is empty; nothing to import")

    v2_type_raw = entry.frontmatter.get("type")
    v2_type = str(v2_type_raw) if v2_type_raw else "memory"

    raw_title = entry.frontmatter.get("title")
    source_title = str(raw_title) if raw_title else _first_line_title(entry.body)
    safe_title, sanitize_note = _sanitize_title(source_title, fallback=source_id)

    hash8 = pl.slugify(source_id)[:12] or source_id[:12]
    slug = pl.slugify(safe_title) or "entry"

    tier_seed = TIER_DECAY_SEED.get(entry.tier, 0.5)
    raw_scope = entry.frontmatter.get("scope")
    v3_scope = _SCOPE_MAP.get(str(raw_scope), "project") if raw_scope else None

    import_meta: dict[str, Any] = {
        "source": "palaia-v2",
        "source_id": source_id,
        "tier": entry.tier,
        "decay_seed": tier_seed,
    }
    for key in ("decay_score", "access_count", "created", "project", "agent"):
        if key in entry.frontmatter:
            import_meta[f"source_{key}"] = entry.frontmatter[key]

    body = entry.body.rstrip("\n") + "\n"
    if sanitize_note:
        body += f"\n- [imported-title] {source_title}\n"
    if v2_type_raw and str(v2_type_raw) not in _TYPE_MAP and str(v2_type_raw) != "task":
        body += f"\n- [import-note] unrecognized v2 type {v2_type_raw!r}, imported as note\n"

    if v2_type == "task":
        permalink = f"inbox/{slug}-{hash8}"
        frontmatter: dict[str, Any] = {
            "type": "capture",
            "tags": ["inbox", *_string_list(entry.frontmatter.get("tags"))],
            "status": "uncurated",
            "import": import_meta,
        }
        task_status = entry.frontmatter.get("status")
        body = (
            "Imported v2 task"
            + (f" (status: {task_status})" if task_status else "")
            + ".\n\n"
            + f"- [entity] {safe_title}\n"
            + "- [why] Imported from palaia v2 as a task; a curator should file "
            "this properly or discard it.\n"
            + f"- [raw] {entry.body.strip()}\n"
        )
        if sanitize_note:
            body += f"- [imported-title] {source_title}\n"
    else:
        v3_type = _TYPE_MAP.get(v2_type, "note")
        folder = _TYPE_FOLDER[v3_type]
        permalink = f"{IMPORT_FOLDER}/{folder}/{slug}-{hash8}"
        frontmatter = {"type": v3_type, "import": import_meta}
        if v3_scope:
            frontmatter["scope"] = v3_scope
        tags = _string_list(entry.frontmatter.get("tags"))
        if tags:
            frontmatter["tags"] = tags

    describe = f"v2 {v2_type} ({entry.tier}) -> {permalink}"
    return MappedNote(
        source_path=entry.source_path,
        permalink=permalink,
        title=safe_title,
        body=body,
        frontmatter=frontmatter,
        describe=describe,
    )


def _first_line_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:80]
    return "Imported v2 entry"


def _sanitize_title(title: str, *, fallback: str) -> tuple[str, bool]:
    """Return a volatility-free title (format spec §4.1), plus whether it changed.

    The writer rejects titles carrying version/date-shaped tokens (§4.1);
    v2 titles are often auto-extracted from free-text content and routinely
    contain exactly that. Rather than treat every such title as unmappable,
    fall back to a stable generic title and preserve the original as an
    ``- [imported-title]`` observation line in the body (volatility rules
    apply to titles/permalinks/link targets only, never to body content).
    """
    if not pl.volatility_violations(title):
        return title, False
    return f"Imported v2 entry {fallback[:8]}", True


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


__all__ = [
    "IMPORT_FOLDER",
    "TIER_DECAY_SEED",
    "V2SourceEntry",
    "V2_TIERS",
    "find_store_root",
    "iter_source_entries",
    "map_v2_entry",
]
