"""Value references (embeds), resolved at read time.

Format spec §5.3: shared values are referenced, never copied. On disk
``![[Base Rate#^rate-limit]]`` stays a reference; recall/read output shows
whatever that block says *now*. There is no propagation machinery and no
stale-copy problem, because nothing is ever copied.

The three failure modes are content, not exceptions (§5.3, warn-first):

* missing target → ``⟦missing: <target>⟧`` plus an ``embed-missing`` warning
* cycle → ``⟦cycle: A → B → A⟧`` plus an ``embed-cycle`` warning, resolution
  stopping at the repeated node
* too deep → ``⟦depth: <target>⟧``; the entry note's own embed is hop 1, hops
  1-8 resolve, hop 9 is capped. No warning code is defined for the cap
  (§9.1's closed list), so none is emitted.

Substitution reuses :func:`palaia_hub.vault.links.iter_links`, which already
skips fenced blocks and inline code spans and reports byte offsets — an
embed inside a code sample is documentation *about* an embed and must render
verbatim.

``docs/vault-format-conformance/resolution/`` is the executable contract:
``tests/recall/test_resolution_conformance.py`` asserts this module's output
against every scenario's ``expected-resolved.md`` byte for byte.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from palaia_hub.vault.links import iter_links

#: Hops that resolve. The entry note's own embed is hop 1 (§5.3), so a
#: 10-note linear chain is the minimal structure that reaches the cap.
MAX_EMBED_DEPTH = 8

#: Warning codes this module emits (§9.1). The depth cap has none by design.
EMBED_MISSING = "embed-missing"
EMBED_CYCLE = "embed-cycle"

_MARKER_OPEN = "⟦"
_MARKER_CLOSE = "⟧"

#: How a cycle chain is serialized inside the marker (§5.3's worked example):
#: note titles along the resolution path, arrow-separated, repeating the node
#: the walk came back to.
_CHAIN_JOIN = " → "

_FENCE_RE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
_ANCHOR_TAIL_RE = re.compile(r"(?:^|[ \t])\^(?P<anchor>[A-Za-z0-9-]{1,32})[ \t]*$")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*$")


def missing_marker(target: str) -> str:
    """``⟦missing: <target>⟧`` — the literal a dangling reference renders as."""
    return f"{_MARKER_OPEN}missing: {target}{_MARKER_CLOSE}"


def cycle_marker(chain: Sequence[str]) -> str:
    """``⟦cycle: A → B → A⟧`` for the note titles along ``chain``."""
    return f"{_MARKER_OPEN}cycle: {_CHAIN_JOIN.join(chain)}{_MARKER_CLOSE}"


def depth_marker(target: str) -> str:
    """``⟦depth: <target>⟧`` — the hop the nesting cap refused to take."""
    return f"{_MARKER_OPEN}depth: {target}{_MARKER_CLOSE}"


@dataclass(frozen=True, slots=True)
class SourceNote:
    """A note an embed can point at: its identity and its raw body."""

    permalink: str
    title: str
    body: str

    @property
    def key(self) -> str:
        """Cycle-detection identity: the permalink, or the title if it has none."""
        return self.permalink or self.title.casefold()


class NoteSource(Protocol):
    """Where the resolver gets embed targets from.

    One method, on purpose: resolution needs nothing but "given the target
    string an author wrote, which note is that (if any)". Implementations
    live in :mod:`palaia_hub.recall.service` (index-backed) and in the
    conformance test (directory-backed).
    """

    def resolve(self, target: str) -> SourceNote | None:
        """The note ``target`` names, or ``None`` if the vault has no such note."""
        ...


@dataclass(frozen=True, slots=True)
class ResolutionWarning:
    """One warning raised while resolving references (§9.1 codes)."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ResolvedText:
    """Resolved output plus what went wrong on the way."""

    text: str
    warnings: tuple[ResolutionWarning, ...] = ()
    inlined: int = 0
    """How many embeds were replaced by real content."""

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(warning.code for warning in self.warnings)


def _code_free_lines(text: str) -> list[tuple[int, str]]:
    """``(index, line)`` for lines outside fenced code blocks."""
    out: list[tuple[int, str]] = []
    fence: str | None = None
    for index, line in enumerate(text.split("\n")):
        match = _FENCE_RE.match(line)
        if fence is not None:
            if match and match.group("fence")[0] == fence[0]:
                fence = None
            continue
        if match:
            fence = match.group("fence")
            continue
        out.append((index, line))
    return out


def block_content(body: str, anchor_id: str) -> str | None:
    """The line carrying ``^anchor_id``, verbatim, or ``None``.

    The *whole line* is the value, anchor included: ``- [rate-limit] 100
    req/min ^rate-limit`` embedded elsewhere renders exactly as it reads in
    its source note, which is what makes an observation line a field other
    notes can point at (§5.4). First occurrence wins, matching the parser's
    ``anchor-duplicate`` rule.
    """
    wanted = anchor_id.casefold()
    for _, line in _code_free_lines(body):
        match = _ANCHOR_TAIL_RE.search(line)
        if match is not None and match.group("anchor").casefold() == wanted:
            return line.rstrip()
    return None


def section_content(body: str, heading: str) -> str | None:
    """The section under ``heading``, up to the next heading of equal-or-higher level."""
    wanted = heading.strip().casefold()
    lines = body.split("\n")
    visible = {index for index, _ in _code_free_lines(body)}
    start: int | None = None
    level = 0
    for index, line in enumerate(lines):
        if index not in visible:
            continue
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        if start is None:
            if match.group("text").strip().casefold() == wanted:
                start = index + 1
                level = len(match.group("hashes"))
            continue
        if len(match.group("hashes")) <= level:
            return "\n".join(lines[start:index]).strip()
    if start is None:
        return None
    return "\n".join(lines[start:]).strip()


def resolve_references(
    body: str,
    *,
    entry: SourceNote,
    source: NoteSource,
    max_depth: int = MAX_EMBED_DEPTH,
    transform: Callable[[str], str] | None = None,
) -> ResolvedText:
    """Inline every embed in ``body``, recursively, with §5.3's failure markers.

    Args:
        body: the entry note's body, already in the form the caller wants it
            (variant filtering, if any, has happened).
        entry: the entry note — its title and key seed the cycle chain, so a
            note embedding itself is caught on the first hop.
        source: how to look targets up.
        max_depth: hops that resolve; hop ``max_depth + 1`` renders
            :func:`depth_marker`.
        transform: applied to every *inlined* note body (and heading
            section) before it is spliced in — this is where per-model
            variant filtering reaches embedded content. Anchored block
            embeds are exempt: a single line addressed by its anchor is the
            value being referenced, not a rendering of the note.
    """
    warnings: list[ResolutionWarning] = []
    counter = _Counter()
    text = _expand(
        body,
        chain_titles=(entry.title,),
        chain_keys=(entry.key,),
        hop=1,
        source=source,
        max_depth=max_depth,
        transform=transform,
        warnings=warnings,
        counter=counter,
    )
    return ResolvedText(text=text, warnings=tuple(warnings), inlined=counter.value)


class _Counter:
    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value = 0


def _expand(
    text: str,
    *,
    chain_titles: tuple[str, ...],
    chain_keys: tuple[str, ...],
    hop: int,
    source: NoteSource,
    max_depth: int,
    transform: Callable[[str], str] | None,
    warnings: list[ResolutionWarning],
    counter: _Counter,
) -> str:
    replacements: list[tuple[int, int, str]] = []
    for link in iter_links(text):
        if not link.embed:
            continue
        written = link.target if link.anchor is None else f"{link.target}#{link.anchor}"
        if hop > max_depth:
            replacements.append((link.start, link.end, depth_marker(link.target)))
            continue
        target = source.resolve(link.target)
        if target is None:
            warnings.append(
                ResolutionWarning(
                    EMBED_MISSING, f"no note in this vault answers to {link.target!r}"
                )
            )
            replacements.append((link.start, link.end, missing_marker(link.target)))
            continue
        if target.key in chain_keys:
            chain = (*chain_titles, target.title)
            warnings.append(ResolutionWarning(EMBED_CYCLE, _CHAIN_JOIN.join(chain)))
            replacements.append((link.start, link.end, cycle_marker(chain)))
            continue
        content = _content_for(target, link.anchor, transform)
        if content is None:
            warnings.append(
                ResolutionWarning(
                    EMBED_MISSING,
                    f"note {target.title!r} has no anchor or heading {link.anchor!r}",
                )
            )
            replacements.append((link.start, link.end, missing_marker(written)))
            continue
        counter.value += 1
        expanded = _expand(
            content,
            chain_titles=(*chain_titles, target.title),
            chain_keys=(*chain_keys, target.key),
            hop=hop + 1,
            source=source,
            max_depth=max_depth,
            transform=transform,
            warnings=warnings,
            counter=counter,
        )
        replacements.append((link.start, link.end, expanded))

    if not replacements:
        return text
    out: list[str] = []
    cursor = 0
    for start, end, value in replacements:
        out.append(text[cursor:start])
        out.append(value)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _content_for(
    target: SourceNote, anchor: str | None, transform: Callable[[str], str] | None
) -> str | None:
    if anchor is None:
        body = transform(target.body) if transform is not None else target.body
        return body.strip()
    if anchor.startswith("^"):
        return block_content(target.body, anchor[1:])
    section = section_content(target.body, anchor)
    if section is None:
        return None
    return transform(section) if transform is not None else section


__all__ = [
    "EMBED_CYCLE",
    "EMBED_MISSING",
    "MAX_EMBED_DEPTH",
    "NoteSource",
    "ResolutionWarning",
    "ResolvedText",
    "SourceNote",
    "block_content",
    "cycle_marker",
    "depth_marker",
    "missing_marker",
    "resolve_references",
    "section_content",
]
