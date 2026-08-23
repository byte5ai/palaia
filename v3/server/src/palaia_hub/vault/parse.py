"""The knowledge-graph parser — markdown text in, a typed model out.

Implements ``docs/vault-format.md`` v1.0 sections 2-6 and 9: frontmatter
normalization, observations, relations, wikilinks/embeds, block anchors and
the warning taxonomy. The golden corpus in
``docs/vault-format-conformance/`` is the executable contract (see
``tests/vault/test_parse_conformance.py``).

Purity (SPEC-103 acceptance criterion): this module does **no I/O**. It
imports only the stdlib and the sibling ``frontmatter``/``permalink``/
``links`` modules, which are themselves pure text transforms (no
filesystem/DB/network access). ``tests/vault/test_parse_purity.py`` enforces
this with a static AST check so a future edit can't silently reintroduce an
I/O dependency.

Warn-first (invariant 3 of the format spec): nothing in here raises on user
content. Anything that doesn't fit the grammar degrades to plain Markdown
plus a warning; ``parse_note`` always returns a ``ParsedNote``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from . import frontmatter as fm
from . import links
from . import permalink as permalink_mod

VAULT_FORMAT_VERSION = 1

#: Entry taxonomy v1 (format spec §6). Unknown types remain valid (warn-first).
KNOWN_TYPES: frozenset[str] = frozenset(
    {
        "note",
        "decision",
        "rule",
        "process",
        "person",
        "project",
        "capture",
        "proposal",
        "meta",
    }
)


# --------------------------------------------------------------------------
# Typed result model (format spec §9)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """One categorized, atomic fact about the note's entity (§5.1)."""

    category: str
    scope: str | None
    text: str
    tags: tuple[str, ...]
    context: str | None
    block_id: str | None
    line: int


@dataclass(frozen=True, slots=True)
class Relation:
    """A typed, directed edge from this note to another entity (§5.2)."""

    type: str
    target: str
    implicit: bool
    context: str | None
    line: int


@dataclass(frozen=True, slots=True)
class Embed:
    """A value reference — ``![[Note]]``, resolved at read time (§5.3)."""

    target: str
    anchor: str | None
    line: int


@dataclass(frozen=True, slots=True)
class Anchor:
    """One ``^block-id`` occurrence, on any line (§5.4)."""

    id: str
    line: int


@dataclass(frozen=True, slots=True)
class Warning:
    """A machine-readable parse warning (§9.1)."""

    code: str
    line: int | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedNote:
    """The canonical parse result of one note (format spec §9)."""

    format_version: int
    path: str
    title: str
    permalink: str | None
    type: str
    tags: tuple[str, ...]
    frontmatter: dict[str, Any]
    body: str
    observations: tuple[Observation, ...] = ()
    relations: tuple[Relation, ...] = ()
    embeds: tuple[Embed, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    warnings: tuple[Warning, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# Regexes — body grammar (format spec §5)
# --------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<bullet>[-*])(?P<ws>[ \t]+)(?P<content>.*)$")

#: cat-char = ALPHA | DIGIT | "-" | "_" | " " (format spec §5.1) — a
#: positive list, not "everything but brackets"; this specifically excludes
#: "^" so a footnote marker like "[^1]" never parses as a category (E6).
_OBS_HEAD_RE = re.compile(
    r"^\[(?P<category>[A-Za-z0-9_ -]{1,64})"
    r"(?:[ \t]*\|[ \t]*(?P<scope>[^\[\]]+?))?"
    r"\][ \t]+(?P<rest>.*)$"
)
_SCOPE_RE = re.compile(r"^(?:default|[a-z]+(?:/[a-z]+[a-z0-9.\-]*)?)$")
_CHECKBOX_CHARS = frozenset(" xX/>-~?!iI")
_DATE_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_SHAPE_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
_DIGITS_SHAPE_RE = re.compile(r"^\d+$")

_ANCHOR_TAIL_RE = re.compile(r"^(?P<text>.*)[ \t]\^(?P<anchor>[A-Za-z0-9-]{1,32})[ \t]*$")
_OBS_CONTEXT_RE = re.compile(r"^(?P<text>.*)[ \t]\((?P<context>[^)]*)\)$")
_TAG_RE = re.compile(r"#([A-Za-z][A-Za-z0-9_-]*)")

_WIKILINK_HEAD_RE = re.compile(r"^\[\[(?P<inner>[^\[\]]*)\]\](?P<tail>.*)$")
_QUOTED_TYPE_RE = re.compile(r'^"(?P<type>[^"]*)"[ \t]+(?P<rest>.*)$')
_BARE_TYPE_RE = re.compile(r"^(?P<type>[a-z]+(?:_[a-z]+)*)[ \t]+(?P<rest>.*)$")
_CONTEXT_ONLY_RE = re.compile(r"^\((?P<context>[^)]*)\)$")

_TRAILING_ANCHOR_RE = re.compile(r"(?:^|[ \t])\^(?P<anchor>[A-Za-z0-9-]{1,32})[ \t]*$")

_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_INDENT_CODE_RE = re.compile(r"^(?: {4,}|\t)")

_KEY_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:")

#: A permalink is already lowercase-hyphenated (§3.1), so the writer-side
#: substring patterns in :mod:`.permalink` are too eager here: a hyphen
#: introduced by slugifying a dot (e.g. "migration-v2-3" from "Migration
#: v2.3") would false-positive as a version tag. A permalink is volatile
#: only when a whole "/"-separated *segment* is itself volatility-shaped
#: (conformance case 38: an ISO-date segment; case 35 is the negative —
#: "migration-v2-3" is not, as a whole segment, a version tag).
_PERMALINK_VOLATILE_SEGMENT_RE = re.compile(
    r"^(?:\d{4}-\d{2}(?:-\d{2})?|v\d+(?:[.-]\d+)+|\d+\.\d+(?:\.\d+)*)$"
)


def _permalink_volatile(value: str) -> bool:
    return any(_PERMALINK_VOLATILE_SEGMENT_RE.match(segment) for segment in value.split("/"))


# --------------------------------------------------------------------------
# Frontmatter-level resolution (format spec §2)
# --------------------------------------------------------------------------


def _stem(path: str) -> str:
    """The filename stem used as the default title (§2.1)."""
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[: -len(".md")]
    return name


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _normalize_tags(value: Any) -> tuple[str, ...]:
    """List-or-comma-string -> a tuple of lowercase strings (§2.1)."""
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip().lower() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            text = fm.coerce_str(item).lower()
            if text:
                out.append(text)
        return tuple(out)
    text = fm.coerce_str(value).lower()
    return (text,) if text else ()


def _fence_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Mirror :func:`frontmatter.parse`'s fence detection for line bookkeeping.

    Returns ``(0, closing_index)`` (0-based index into ``lines``) when a
    fence opens at line 1, ``(0, -1)`` when it opens but never closes, or
    ``None`` when there is no fence at all.
    """
    if not lines or lines[0].strip() != "---":
        return None
    for number, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return (0, number)
    return (0, -1)


def _frontmatter_key_lines(lines: list[str], closing_idx: int) -> dict[str, int]:
    """Raw 1-based line number of each top-level frontmatter key."""
    result: dict[str, int] = {}
    for raw_line_no, raw_line in enumerate(lines[1:closing_idx], start=2):
        match = _KEY_LINE_RE.match(raw_line)
        if match and match.group(1) not in result:
            result[match.group(1)] = raw_line_no
    return result


def _resolve_title(
    fm_dict: dict[str, Any], path: str, warnings: list[Warning], key_lines: dict[str, int]
) -> str:
    if "title" not in fm_dict:
        warnings.append(Warning("title-defaulted"))
        return _stem(path)
    raw = fm_dict["title"]
    if isinstance(raw, list):
        warnings.append(Warning("title-coerced", line=key_lines.get("title")))
        if not raw:
            return _stem(path)
        return fm.coerce_str(raw[0])
    return fm.coerce_str(raw)


def _resolve_permalink(
    fm_dict: dict[str, Any], warnings: list[Warning], key_lines: dict[str, int]
) -> str | None:
    if "permalink" not in fm_dict:
        warnings.append(Warning("permalink-missing"))
        return None
    value = fm.coerce_str(fm_dict["permalink"])
    if not permalink_mod.is_canonical(value):
        warnings.append(Warning("permalink-noncanonical", line=key_lines.get("permalink")))
    return value


def _resolve_type(
    fm_dict: dict[str, Any], warnings: list[Warning], key_lines: dict[str, int]
) -> str:
    if "type" not in fm_dict:
        return "note"
    value = fm.coerce_str(fm_dict["type"])
    if value not in KNOWN_TYPES:
        warnings.append(Warning("type-unknown", line=key_lines.get("type")))
    return value


def _check_format_version(
    fm_dict: dict[str, Any], warnings: list[Warning], key_lines: dict[str, int]
) -> None:
    if "vault_format" not in fm_dict:
        return
    raw = fm_dict["vault_format"]
    try:
        version = int(raw)
    except (TypeError, ValueError):
        version = -1
    if version != VAULT_FORMAT_VERSION:
        warnings.append(Warning("format-version", line=key_lines.get("vault_format")))


def _build_frontmatter_field(
    fm_dict_raw: dict[str, Any],
    title: str,
    type_value: str,
    tags: tuple[str, ...],
    permalink_value: str | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {key: _json_safe(value) for key, value in fm_dict_raw.items()}
    out["title"] = title
    out["type"] = type_value
    out["tags"] = list(tags)
    if permalink_value is not None:
        out["permalink"] = permalink_value
    else:
        out.pop("permalink", None)
    return out


def _sort_warnings(warnings: list[Warning]) -> list[Warning]:
    """README ordering: lineless warnings first (alphabetical), then by
    (line ascending, code alphabetically)."""

    def key(warning: Warning) -> tuple[int, Any, Any]:
        if warning.line is None:
            return (0, warning.code, "")
        return (1, warning.line, warning.code)

    return sorted(warnings, key=key)


# --------------------------------------------------------------------------
# Body grammar (format spec §5)
# --------------------------------------------------------------------------


def _category_excluded(category: str) -> bool:
    """E1 (checkbox markers) and E4 (date/time/purely-numeric categories)."""
    if len(category) == 1 and category in _CHECKBOX_CHARS:
        return True
    return bool(
        _DATE_SHAPE_RE.match(category)
        or _TIME_SHAPE_RE.match(category)
        or _DIGITS_SHAPE_RE.match(category)
    )


def _code_excluded_lines(body_lines: list[str]) -> set[int]:
    """0-based indices of fenced (E2) or 4-space/tab indented code lines."""
    excluded: set[int] = set()
    fence_char: str | None = None
    for idx, line in enumerate(body_lines):
        match = _FENCE_RE.match(line)
        if fence_char is not None:
            excluded.add(idx)
            if match and match.group(1)[0] == fence_char:
                fence_char = None
            continue
        if match:
            fence_char = match.group(1)[0]
            excluded.add(idx)
            continue
        if _INDENT_CODE_RE.match(line):
            excluded.add(idx)
    return excluded


def _split_wikilink_inner(inner: str) -> tuple[str, str | None, str | None]:
    display: str | None = None
    anchor: str | None = None
    if "|" in inner:
        inner, display = inner.split("|", 1)
    if "#" in inner:
        inner, anchor = inner.split("#", 1)
    return inner.strip(), anchor, display


def _try_observation(content: str, line: int) -> Observation | None:
    match = _OBS_HEAD_RE.match(content)
    if not match:
        return None
    category_raw = match.group("category")
    if _category_excluded(category_raw):
        return None
    category = category_raw.rstrip()
    scope_raw = match.group("scope")
    scope: str | None = None
    if scope_raw is not None:
        scope_raw = scope_raw.strip()
        if not _SCOPE_RE.match(scope_raw):
            return None
        scope = scope_raw
    rest = match.group("rest")
    block_id: str | None = None
    anchor_match = _ANCHOR_TAIL_RE.match(rest)
    if anchor_match:
        block_id = anchor_match.group("anchor")
        rest = anchor_match.group("text")
    rest_stripped = rest.rstrip()
    context_match = _OBS_CONTEXT_RE.match(rest_stripped)
    if context_match:
        context = context_match.group("context")
        text = context_match.group("text").rstrip()
    else:
        context = None
        text = rest_stripped
    tags = tuple(_TAG_RE.findall(text))
    return Observation(
        category=category,
        scope=scope,
        text=text,
        tags=tags,
        context=context,
        block_id=block_id,
        line=line,
    )


def _try_relation(content: str, line: int) -> Relation | None:
    direct = _WIKILINK_HEAD_RE.match(content)
    rel_type = "links_to"
    wiki_match = direct
    if wiki_match is None:
        quoted = _QUOTED_TYPE_RE.match(content)
        if quoted:
            rel_type = quoted.group("type")
            wiki_match = _WIKILINK_HEAD_RE.match(quoted.group("rest"))
        else:
            bare = _BARE_TYPE_RE.match(content)
            if not bare:
                return None
            rel_type = bare.group("type")
            wiki_match = _WIKILINK_HEAD_RE.match(bare.group("rest"))
        if wiki_match is None:
            return None
    target, _anchor, _display = _split_wikilink_inner(wiki_match.group("inner"))
    tail = wiki_match.group("tail").strip()
    context: str | None = None
    if tail:
        context_match = _CONTEXT_ONLY_RE.match(tail)
        if not context_match:
            return None
        context = context_match.group("context")
    return Relation(type=rel_type, target=target, implicit=False, context=context, line=line)


def _variant_warnings(observations: list[Observation]) -> list[Warning]:
    """§5.1 per-model variants: a group with only scoped lines and no base."""
    warnings: list[Warning] = []
    groups: list[list[Observation]] = []
    for obs in observations:
        if groups and groups[-1][0].category == obs.category:
            groups[-1].append(obs)
        else:
            groups.append([obs])
    for group in groups:
        if all(o.scope is not None for o in group):
            warnings.append(Warning("variant-no-base", line=group[-1].line))
    return warnings


@dataclass(frozen=True, slots=True)
class _BodyResult:
    observations: list[Observation]
    relations: list[Relation]
    embeds: list[Embed]
    anchors: list[Anchor]
    warnings: list[Warning]


def _parse_body(body_text: str, first_raw_line: int) -> _BodyResult:
    body_lines = body_text.split("\n")
    excluded_idx = _code_excluded_lines(body_lines)

    observations: list[Observation] = []
    explicit_relations: list[Relation] = []
    anchors: list[Anchor] = []
    warnings: list[Warning] = []
    consumed_lines: set[int] = set()
    seen_anchor_ids: set[str] = set()

    for idx, raw_line_text in enumerate(body_lines):
        raw_line_no = first_raw_line + idx
        if idx not in excluded_idx:
            anchor_match = _TRAILING_ANCHOR_RE.search(raw_line_text)
            if anchor_match:
                anchor_id = anchor_match.group("anchor")
                anchors.append(Anchor(id=anchor_id, line=raw_line_no))
                if anchor_id in seen_anchor_ids:
                    warnings.append(Warning("anchor-duplicate", line=raw_line_no))
                else:
                    seen_anchor_ids.add(anchor_id)
        if idx in excluded_idx:
            continue
        bullet_match = _BULLET_RE.match(raw_line_text)
        if not bullet_match:
            continue
        content = bullet_match.group("content")
        observation = _try_observation(content, raw_line_no)
        if observation is not None:
            observations.append(observation)
            continue
        relation = _try_relation(content, raw_line_no)
        if relation is not None:
            explicit_relations.append(relation)
            consumed_lines.add(raw_line_no)

    warnings.extend(_variant_warnings(observations))

    embeds: list[Embed] = []
    implicit_relations: list[Relation] = []
    for wikilink in links.iter_links(body_text):
        raw_line = first_raw_line + wikilink.line - 1
        if wikilink.embed:
            embeds.append(Embed(target=wikilink.target, anchor=wikilink.anchor, line=raw_line))
            continue
        if raw_line in consumed_lines:
            continue
        implicit_relations.append(
            Relation(
                type="links_to",
                target=wikilink.target,
                implicit=True,
                context=None,
                line=raw_line,
            )
        )

    all_relations = sorted(explicit_relations + implicit_relations, key=lambda r: r.line)
    for relation in all_relations:
        if permalink_mod.volatility_violations(relation.target):
            warnings.append(Warning("volatile-name", line=relation.line))

    return _BodyResult(observations, all_relations, embeds, anchors, warnings)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def parse_note(text: str, path: str) -> ParsedNote:
    """Parse ``text`` (the raw content of the note at ``path``) into a
    :class:`ParsedNote`. Never raises on user content (invariant 3)."""
    normalized = fm.normalize_newlines(text)
    lines = normalized.split("\n")
    bounds = _fence_bounds(lines)
    parsed_fm = fm.parse(text)

    if bounds is not None and bounds[1] >= 0:
        body_start_idx = bounds[1] + 1
        key_lines = _frontmatter_key_lines(lines, bounds[1])
    else:
        body_start_idx = 0
        key_lines = {}

    warnings: list[Warning] = []

    if parsed_fm.malformed:
        warnings.extend(
            [
                Warning("frontmatter-malformed"),
                Warning("title-defaulted"),
                Warning("permalink-missing"),
            ]
        )
        title = _stem(path)
        permalink_value: str | None = None
        type_value = "note"
        tags: tuple[str, ...] = ()
        fm_dict_raw: dict[str, Any] = {}
    else:
        fm_dict_raw = dict(parsed_fm.frontmatter)
        title = _resolve_title(fm_dict_raw, path, warnings, key_lines)
        permalink_value = _resolve_permalink(fm_dict_raw, warnings, key_lines)
        type_value = _resolve_type(fm_dict_raw, warnings, key_lines)
        tags = _normalize_tags(fm_dict_raw.get("tags"))
        _check_format_version(fm_dict_raw, warnings, key_lines)

    if permalink_mod.volatility_violations(title):
        warnings.append(Warning("volatile-name", line=key_lines.get("title")))
    if permalink_value and _permalink_volatile(permalink_value):
        warnings.append(Warning("volatile-name", line=key_lines.get("permalink")))

    body_text = "\n".join(lines[body_start_idx:])
    body_result = _parse_body(body_text, body_start_idx + 1)
    warnings.extend(body_result.warnings)

    final_warnings = _sort_warnings(warnings)
    frontmatter_field = _build_frontmatter_field(
        fm_dict_raw, title, type_value, tags, permalink_value
    )

    return ParsedNote(
        format_version=VAULT_FORMAT_VERSION,
        path=path,
        title=title,
        permalink=permalink_value,
        type=type_value,
        tags=tags,
        frontmatter=frontmatter_field,
        body=body_text,
        observations=tuple(body_result.observations),
        relations=tuple(body_result.relations),
        embeds=tuple(body_result.embeds),
        anchors=tuple(body_result.anchors),
        warnings=tuple(final_warnings),
    )


def render_note(note: ParsedNote) -> str:
    """Serialize ``note`` back to canonical text (§2.2). Round-trip stable:
    ``parse_note(render_note(parse_note(text, path)), path)`` reaches a fixed
    point (idempotent past the first canonicalization)."""
    return fm.render(dict(note.frontmatter), note.body)


def to_json(note: ParsedNote) -> dict[str, Any]:
    """Serialize ``note`` to the canonical JSON shape (format spec §9)."""
    warnings_json: list[dict[str, Any]] = []
    for warning in note.warnings:
        entry: dict[str, Any] = {"code": warning.code}
        if warning.line is not None:
            entry["line"] = warning.line
        if warning.detail is not None:
            entry["detail"] = warning.detail
        warnings_json.append(entry)

    return {
        "format_version": note.format_version,
        "path": note.path,
        "title": note.title,
        "permalink": note.permalink,
        "type": note.type,
        "tags": list(note.tags),
        "frontmatter": note.frontmatter,
        "observations": [
            {
                "category": o.category,
                "scope": o.scope,
                "text": o.text,
                "tags": list(o.tags),
                "context": o.context,
                "block_id": o.block_id,
                "line": o.line,
            }
            for o in note.observations
        ],
        "relations": [
            {
                "type": r.type,
                "target": r.target,
                "implicit": r.implicit,
                "context": r.context,
                "line": r.line,
            }
            for r in note.relations
        ],
        "embeds": [
            {"target": e.target, "anchor": e.anchor, "line": e.line} for e in note.embeds
        ],
        "anchors": [{"id": a.id, "line": a.line} for a in note.anchors],
        "warnings": warnings_json,
    }
