"""Frontmatter handling — raw YAML only.

Scope discipline: this module reads and writes the YAML block *as data* so
the engine can maintain the identity keys it owns (``title``, ``permalink``,
``created``/``modified``, ``aliases``, ``origin``) and render the canonical
write form of format spec §2.2. It deliberately does **not** interpret note
*semantics* — observations, relations, embeds and the warning taxonomy are
SPEC-103's job. Unknown keys are preserved verbatim.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yaml

FENCE = "---"

#: Canonical key order for engine writes (format spec §2.1 table order);
#: unknown keys follow, sorted alphabetically (§2.2).
KEY_ORDER: tuple[str, ...] = (
    "title",
    "permalink",
    "type",
    "tags",
    "created",
    "modified",
    "scope",
    "origin",
    "aliases",
    "status",
    "capture_id",
    "schema",
)

_BOM = "﻿"


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """The raw split of a note file into frontmatter mapping and body."""

    frontmatter: dict[str, Any]
    body: str
    has_fence: bool
    malformed: bool


def normalize_newlines(text: str) -> str:
    """Strip a BOM and normalize CRLF/CR to LF (engine reads tolerate both)."""
    if text.startswith(_BOM):
        text = text[len(_BOM) :]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse(text: str) -> ParsedFile:
    """Split ``text`` into frontmatter and body.

    A file with no ``---`` fence at all is an ordinary plain note (format
    spec §2): no frontmatter, no malformed flag. ``malformed`` is set only
    when a fence is present but broken — unparseable YAML, a non-mapping
    document, or an opening fence that is never closed.
    """
    text = normalize_newlines(text)
    if not text.startswith(FENCE + "\n") and text.rstrip() != FENCE:
        return ParsedFile(frontmatter={}, body=text, has_fence=False, malformed=False)

    lines = text.split("\n")
    closing: int | None = None
    for number, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            closing = number
            break
    if closing is None:
        return ParsedFile(frontmatter={}, body=text, has_fence=True, malformed=True)

    raw_yaml = "\n".join(lines[1:closing])
    body = "\n".join(lines[closing + 1 :])
    body = body[1:] if body.startswith("\n") else body
    try:
        loaded = yaml.safe_load(raw_yaml) if raw_yaml.strip() else {}
    except yaml.YAMLError:
        return ParsedFile(frontmatter={}, body=body, has_fence=True, malformed=True)
    if loaded is None:
        return ParsedFile(frontmatter={}, body=body, has_fence=True, malformed=False)
    if not isinstance(loaded, dict):
        return ParsedFile(frontmatter={}, body=body, has_fence=True, malformed=True)
    frontmatter = {str(key): value for key, value in loaded.items()}
    return ParsedFile(frontmatter=frontmatter, body=body, has_fence=True, malformed=False)


def ordered_keys(frontmatter: Mapping[str, Any]) -> list[str]:
    """Return ``frontmatter``'s keys in canonical write order (§2.2)."""
    known = [key for key in KEY_ORDER if key in frontmatter]
    unknown = sorted(key for key in frontmatter if key not in KEY_ORDER)
    return known + unknown


def render(frontmatter: Mapping[str, Any], body: str) -> str:
    """Render the canonical write form: ordered keys, LF, one blank line.

    Quoting is left to PyYAML, which quotes only where YAML requires it.
    Leaf collections render in flow style (``tags: [infra]``) to match the
    examples in the format spec.
    """
    if not frontmatter:
        return _normalize_body(body)
    chunks = [_render_key(key, frontmatter[key]) for key in ordered_keys(frontmatter)]
    return f"{FENCE}\n" + "\n".join(chunks) + f"\n{FENCE}\n\n" + _normalize_body(body)


def _render_key(key: str, value: Any) -> str:
    if isinstance(value, list | dict | tuple | set):
        flow = yaml.safe_dump(
            _plain(value),
            default_flow_style=True,
            allow_unicode=True,
            sort_keys=False,
            width=1_000_000,
        ).strip()
        return f"{key}: {flow}"
    dumped = yaml.safe_dump(
        {key: value},
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )
    return dumped.rstrip("\n")


def _plain(value: Any) -> Any:
    """Convert tuples/sets to lists so PyYAML emits plain collections."""
    if isinstance(value, tuple | set):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _normalize_body(body: str) -> str:
    body = normalize_newlines(body).lstrip("\n")
    if not body:
        return ""
    return body if body.endswith("\n") else body + "\n"


def coerce_str(value: Any) -> str:
    """Coerce a YAML scalar to a string (§2: dates/numbers/bools arrive native)."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def string_value(frontmatter: Mapping[str, Any], key: str) -> tuple[str | None, bool]:
    """Return ``(value, coerced)`` for a string-typed key.

    A list value coerces to its first item (warning ``title-coerced`` in
    SPEC-103's taxonomy); a comma-bearing plain string is *not* split.
    """
    if key not in frontmatter:
        return None, False
    raw = frontmatter[key]
    if isinstance(raw, list):
        if not raw:
            return None, True
        return coerce_str(raw[0]), True
    if isinstance(raw, str):
        return raw, False
    return coerce_str(raw), True


def string_list(value: Any) -> list[str]:
    """Normalize a list-or-comma-string frontmatter value to a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, Iterable) and not isinstance(value, bytes | Mapping):
        return [coerce_str(item) for item in value if coerce_str(item)]
    return [coerce_str(value)]


def utc_now_iso() -> str:
    """Return the current time as an ISO 8601 UTC timestamp (seconds precision)."""
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
