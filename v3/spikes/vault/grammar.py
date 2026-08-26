"""Minimal parser for the toy vault note grammar used by this spike.

NOT the formal v3 vault grammar (SPEC-004 defines that). This is just enough
to prove the round-trip / index / rebuild loop end to end, per the shape
described in v3/research/basic-memory.md §1:

    ---
    title: <str>
    type: <str>
    permalink: <str>
    tags: [<str>, ...]
    created: <iso8601>
    modified: <iso8601>
    ---

    # <title>

    <freeform prose paragraph, may contain [[Wikilinks]] -> implicit links_to>

    ## Observations
    - [category] content text #tag1 #tag2 (optional context)

    ## Relations
    - relation_type [[Target]] (optional context)

No external dependency beyond PyYAML, which every script in this spike that
imports this module already declares in its own PEP 723 header.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
OBS_HEADER_RE = re.compile(r"^##\s*Observations\s*$", re.MULTILINE)
REL_HEADER_RE = re.compile(r"^##\s*Relations\s*$", re.MULTILINE)
NEXT_HEADER_RE = re.compile(r"^##\s+\S", re.MULTILINE)

OBS_LINE_RE = re.compile(
    r"^-\s*\[(?P<category>[^\]]+)\]\s*(?P<rest>.*)$"
)
REL_LINE_RE = re.compile(
    r"^-\s*(?P<rel_type>[a-zA-Z0-9_\-]+)\s+\[\[(?P<target>[^\]]+)\]\]\s*(?:\((?P<context>[^)]*)\))?\s*$"
)
TAG_RE = re.compile(r"#(\w+)")
CONTEXT_RE = re.compile(r"\(([^)]*)\)\s*$")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class Observation:
    entity_permalink: str
    category: str
    content: str
    tags: list[str] = field(default_factory=list)
    context: str | None = None


@dataclass
class Relation:
    source_permalink: str
    relation_type: str
    target_raw: str
    context: str | None = None


@dataclass
class Entity:
    permalink: str
    path: str
    title: str
    type: str
    tags: list[str]
    created: str
    modified: str
    body: str
    observations: list[Observation] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


class ParseError(ValueError):
    pass


def _split_section(body: str, header_re: re.Pattern) -> str | None:
    m = header_re.search(body)
    if not m:
        return None
    start = m.end()
    rest = body[start:]
    nxt = NEXT_HEADER_RE.search(rest)
    return rest[: nxt.start()] if nxt else rest


def parse_note(text: str, path: str) -> Entity:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ParseError(f"{path}: missing/malformed frontmatter block")
    fm_raw, body = m.group(1), m.group(2)
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"{path}: invalid YAML frontmatter: {exc}") from exc

    for required in ("title", "permalink"):
        if required not in fm:
            raise ParseError(f"{path}: frontmatter missing required key '{required}'")

    permalink = str(fm["permalink"])
    entity = Entity(
        permalink=permalink,
        path=path,
        title=str(fm["title"]),
        type=str(fm.get("type", "note")),
        tags=list(fm.get("tags", []) or []),
        created=str(fm.get("created", "")),
        modified=str(fm.get("modified", "")),
        body=body,
    )

    obs_section = _split_section(body, OBS_HEADER_RE) or ""
    for line in obs_section.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        om = OBS_LINE_RE.match(line)
        if not om:
            continue
        rest = om.group("rest")
        ctx_m = CONTEXT_RE.search(rest)
        context = ctx_m.group(1) if ctx_m else None
        rest_wo_ctx = rest[: ctx_m.start()] if ctx_m else rest
        tags = TAG_RE.findall(rest_wo_ctx)
        content = TAG_RE.sub("", rest_wo_ctx).strip()
        entity.observations.append(
            Observation(
                entity_permalink=permalink,
                category=om.group("category").strip(),
                content=content,
                tags=tags,
                context=context,
            )
        )

    rel_section = _split_section(body, REL_HEADER_RE) or ""
    explicit_targets: set[str] = set()
    for line in rel_section.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        rm = REL_LINE_RE.match(line)
        if not rm:
            continue
        target = rm.group("target").strip()
        explicit_targets.add(target)
        entity.relations.append(
            Relation(
                source_permalink=permalink,
                relation_type=rm.group("rel_type"),
                target_raw=target,
                context=rm.group("context"),
            )
        )

    # Implicit links_to: any [[Wikilink]] in prose outside the Relations
    # section that wasn't already captured as an explicit relation target.
    prose = body
    rel_m = REL_HEADER_RE.search(body)
    if rel_m:
        prose = body[: rel_m.start()]
    for wl in WIKILINK_RE.findall(prose):
        target = wl.strip()
        if target in explicit_targets:
            continue
        entity.relations.append(
            Relation(
                source_permalink=permalink,
                relation_type="links_to",
                target_raw=target,
                context=None,
            )
        )
        explicit_targets.add(target)

    return entity


def parse_file(fs_path: str, vault_root: str) -> Entity:
    with open(fs_path, encoding="utf-8") as f:
        text = f.read()
    rel_path = fs_path[len(vault_root) :].lstrip("/")
    return parse_note(text, rel_path)
