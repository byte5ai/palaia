"""Read a basic-memory vault and map its entities to v3 notes.

**Clean-room, concept-only, license-safe.** basic-memory is AGPL-3.0
(ADR-002); no code or literal grammar definitions from that project are
read or copied. This module implements the mapping described in
``v3/research/basic-memory.md`` §1 (a public concept dossier, not their
source) against v3's own format-spec grammar (``docs/vault-format.md``
§2/§5), documented in full in ``docs/import-mappings.md``.

Mapping:

- Frontmatter ``title``/``type``/``tags``/``created``/``modified``/``schema``
  copy across 1:1 (same key names in both formats); unknown custom keys are
  preserved verbatim, same as v3's own §2 rule.
- The old ``permalink`` is never reused as-is: v3 mints its own permalink
  (deterministic, from the old permalink so re-imports are idempotent) and
  keeps the old value as an alias, per the interop note in
  ``docs/vault-format.md`` §11.
- basic-memory observations are **already** ``- [category] text #tags
  (context)`` — identical surface grammar to v3's (§5.1) — *except* a bare
  bullet with no ``[category]`` is implicitly a ``Note``-category
  observation in basic-memory, whereas v3's explicit-only rule (§5.1) treats
  the same bare bullet as plain prose. To preserve that observation instead
  of silently downgrading it to prose, a bare bullet that is not a checkbox
  (E1), not a bare/quoted-type relation line, and not a bare wikilink line
  (which v3 already treats as an explicit ``links_to``, matching bm's own
  fallback) is rewritten to ``- [note] <text>``, per the interop note.
- basic-memory relation lines already sharing v3's ``rel-type
  [[Target]] (context)`` shape need no rewriting; a relation line carrying
  extra prose after the wikilink (bm tolerates this, v3's §5.2 does not) is
  left as-is and parses as plain prose with an implicit ``links_to`` — the
  interop note's "prose relations import as prose".
- Fenced code blocks and blockquotes are left untouched (the rewrite never
  reaches into them, matching E2/E3).
- Non-``.md`` files (bm indexes them as opaque attachment entities) are not
  imported in v1 — reported as unmappable, since v3 has no attachment
  ingestion path yet.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from palaia_hub.vault import frontmatter as fm
from palaia_hub.vault import permalink as pl

from .models import MappedNote, SkippedItem

IMPORT_FOLDER = "imported/basic-memory"

#: Frontmatter keys v3 sets itself and must not blindly copy through.
_ENGINE_OWNED_KEYS = frozenset({"title", "permalink", "aliases", "origin"})

#: Format spec §2.1 keys that pass straight through unchanged when present.
_PASSTHROUGH_KEYS = ("type", "tags", "schema")

_BULLET_RE = re.compile(r"^(?P<indent>\s*)(?P<mark>[-*])\s+(?P<rest>.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_CATEGORY_RE = re.compile(r"^\[(?P<cat>[^\[\]]{1,64})\]\s?")
_BARE_OR_QUOTED_RELTYPE_RE = re.compile(r'^(?:[a-z][a-z0-9_]*|"[^"]+")\s+\[\[')
_WIKILINK_ONLY_RE = re.compile(r"^\[\[[^\[\]]+\]\]\s*(\([^()]*\))?\s*$")


@dataclass(frozen=True, slots=True)
class BMSourceEntry:
    """One raw basic-memory file, before mapping."""

    source_path: str
    is_markdown: bool
    frontmatter: dict[str, Any]
    body: str
    malformed_frontmatter: bool = False


def iter_source_entries(vault_root: Path) -> Iterator[BMSourceEntry]:
    """Yield every file in a basic-memory vault, sorted, skipping ``.obsidian``/VCS dirs."""
    ignored_dirs = {".obsidian", ".git", ".basic-memory", ".trash"}
    paths: list[Path] = []
    stack = [vault_root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name not in ignored_dirs:
                    stack.append(child)
                continue
            paths.append(child)
    for path in sorted(paths):
        relative = path.relative_to(vault_root).as_posix()
        if path.suffix.lower() != ".md":
            yield BMSourceEntry(source_path=relative, is_markdown=False, frontmatter={}, body="")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            yield BMSourceEntry(
                source_path=relative,
                is_markdown=True,
                frontmatter={"__undecodable__": True},
                body="",
            )
            continue
        parsed = fm.parse(text)
        yield BMSourceEntry(
            source_path=relative,
            is_markdown=True,
            frontmatter=parsed.frontmatter,
            body=parsed.body,
            malformed_frontmatter=parsed.malformed,
        )


def map_bm_entry(entry: BMSourceEntry) -> MappedNote | SkippedItem:
    """Map one basic-memory entity to a v3 :class:`MappedNote`."""
    if not entry.is_markdown:
        return SkippedItem(
            entry.source_path,
            "non-markdown attachment; v3 import does not ingest attachments yet",
        )
    if entry.frontmatter.get("__undecodable__"):
        return SkippedItem(entry.source_path, "cannot decode file as UTF-8 text")
    if entry.malformed_frontmatter:
        return SkippedItem(
            entry.source_path,
            "frontmatter fence present but unparseable; fix the source YAML and re-run",
        )

    old_permalink_raw = entry.frontmatter.get("permalink")
    old_permalink = str(old_permalink_raw) if old_permalink_raw else None
    stable_key = old_permalink or entry.source_path
    hash8 = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:10]

    raw_title = entry.frontmatter.get("title")
    source_title = str(raw_title) if raw_title else _stem(entry.source_path)
    safe_title, sanitize_note = _sanitize_title(source_title, fallback=hash8)
    slug = pl.slugify(safe_title) or "entry"
    permalink = f"{IMPORT_FOLDER}/{slug}-{hash8}"

    frontmatter: dict[str, Any] = {}
    for key in _PASSTHROUGH_KEYS:
        if key in entry.frontmatter:
            frontmatter[key] = entry.frontmatter[key]
    frontmatter.setdefault("type", "note")

    aliases: list[str] = []
    if old_permalink and old_permalink != permalink:
        aliases.append(old_permalink)
    if aliases:
        frontmatter["aliases"] = aliases

    import_meta: dict[str, Any] = {"source": "basic-memory", "source_path": entry.source_path}
    if old_permalink:
        import_meta["source_permalink"] = old_permalink
    for key in ("created", "modified"):
        if key in entry.frontmatter:
            import_meta[f"source_{key}"] = entry.frontmatter[key]
    frontmatter["import"] = import_meta

    for key, value in entry.frontmatter.items():
        if key in _ENGINE_OWNED_KEYS or key in _PASSTHROUGH_KEYS or key in ("created", "modified"):
            continue
        frontmatter.setdefault(key, value)

    body = _rewrite_bare_observations(entry.body)
    if sanitize_note:
        body = body.rstrip("\n") + f"\n\n- [imported-title] {source_title}\n"

    describe = f"basic-memory note -> {permalink}"
    return MappedNote(
        source_path=entry.source_path,
        permalink=permalink,
        title=safe_title,
        body=body,
        frontmatter=frontmatter,
        describe=describe,
    )


def _stem(relative: str) -> str:
    name = relative.rsplit("/", 1)[-1]
    return name[: -len(".md")] if name.endswith(".md") else name


def _sanitize_title(title: str, *, fallback: str) -> tuple[str, bool]:
    """Same volatility fallback as the v2 importer (format spec §4.1)."""
    if not pl.volatility_violations(title):
        return title, False
    return f"Imported basic-memory note {fallback[:8]}", True


def _rewrite_bare_observations(body: str) -> str:
    """Rewrite bare, uncategorized bullets to explicit ``[note]`` observations.

    Skips lines inside fenced code blocks (``` / ~~~) and blockquotes (``>``
    prefix) entirely — those are left byte-for-byte untouched, matching
    v3's own E2/E3 exclusions.
    """
    lines = body.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or line.lstrip().startswith(">"):
            out.append(line)
            continue
        out.append(_rewrite_line(line))
    return "\n".join(out)


def _rewrite_line(line: str) -> str:
    match = _BULLET_RE.match(line)
    if not match:
        return line
    rest = match.group("rest")
    if not rest.strip():
        return line

    if _CATEGORY_RE.match(rest):
        # Already carries a bracketed category (explicit observation, or a
        # checkbox task marker like `[ ]`/`[x]`) — leave it exactly as-is.
        return line

    if _BARE_OR_QUOTED_RELTYPE_RE.match(rest):
        return line  # explicit relation line — leave alone
    if _WIKILINK_ONLY_RE.match(rest):
        return line  # bare wikilink bullet — already an explicit links_to

    indent = match.group("indent")
    mark = match.group("mark")
    return f"{indent}{mark} [note] {rest}"


__all__ = ["IMPORT_FOLDER", "BMSourceEntry", "iter_source_entries", "map_bm_entry"]
