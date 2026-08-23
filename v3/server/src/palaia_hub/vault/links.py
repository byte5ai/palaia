"""Wikilink scanning and target rewriting.

Only what the engine needs to keep identity intact: find ``[[target]]`` /
``![[target]]`` occurrences and rewrite their *target* part while preserving
``#anchor`` and ``|display`` exactly as the author wrote them (format spec
§4.2 step 3, §5.2, §5.3). Relation/observation *semantics* are SPEC-103's.

Code is never rewritten: fenced blocks (``` / ~~~) and inline code spans are
skipped, a deliberately conservative subset of the format spec's E2
exclusion — rewriting a link inside a user's code sample would corrupt
content the engine does not own. Four-space-indented code blocks are *not*
excluded here on purpose: indistinguishable from nested list items without
block-level parsing, and missing a nested ``- [[Target]]`` during a rename
would leave a dangling backlink, which is the worse failure.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

_LINK_RE = re.compile(r"(?P<embed>!)?\[\[(?P<inner>[^\[\]\n]*)\]\]")
_FENCE_RE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True, slots=True)
class WikiLink:
    """One ``[[target#anchor|display]]`` occurrence in a note body."""

    line: int
    target: str
    anchor: str | None
    display: str | None
    embed: bool
    start: int
    end: int

    @property
    def text(self) -> str:
        """Render the link back to its source form."""
        inner = self.target
        if self.anchor is not None:
            inner = f"{inner}#{self.anchor}"
        if self.display is not None:
            inner = f"{inner}|{self.display}"
        return f"{'!' if self.embed else ''}[[{inner}]]"


def _split_inner(inner: str) -> tuple[str, str | None, str | None]:
    display: str | None = None
    anchor: str | None = None
    if "|" in inner:
        inner, display = inner.split("|", 1)
    if "#" in inner:
        inner, anchor = inner.split("#", 1)
    return inner, anchor, display


def _code_free_lines(text: str) -> Iterator[tuple[int, int, str]]:
    """Yield ``(line_number, offset, line)`` for lines outside code blocks."""
    offset = 0
    fence: str | None = None
    for number, line in enumerate(text.split("\n"), start=1):
        stripped_match = _FENCE_RE.match(line)
        if fence is not None:
            if stripped_match and stripped_match.group("fence")[0] == fence[0]:
                fence = None
            offset += len(line) + 1
            continue
        if stripped_match:
            fence = stripped_match.group("fence")
            offset += len(line) + 1
            continue
        yield number, offset, line
        offset += len(line) + 1


def _masked(line: str) -> str:
    """Blank out inline code spans so links inside them are not matched."""
    return _INLINE_CODE_RE.sub(lambda match: " " * len(match.group(0)), line)


def iter_links(text: str) -> Iterator[WikiLink]:
    """Yield every wikilink/embed in ``text`` outside code."""
    for number, offset, line in _code_free_lines(text):
        for match in _LINK_RE.finditer(_masked(line)):
            target, anchor, display = _split_inner(match.group("inner"))
            yield WikiLink(
                line=number,
                target=target.strip(),
                anchor=anchor,
                display=display,
                embed=match.group("embed") is not None,
                start=offset + match.start(),
                end=offset + match.end(),
            )


def rewrite_targets(text: str, resolve: Callable[[str], str | None]) -> tuple[str, int]:
    """Rewrite link targets via ``resolve``; return ``(new_text, count)``.

    ``resolve`` receives a link target as written and returns its replacement,
    or ``None`` to leave the link untouched. Anchors and display text are
    preserved verbatim.
    """
    links = [link for link in iter_links(text)]
    replacements: list[tuple[int, int, str]] = []
    for link in links:
        replacement = resolve(link.target)
        if replacement is None or replacement == link.target:
            continue
        rewritten = WikiLink(
            line=link.line,
            target=replacement,
            anchor=link.anchor,
            display=link.display,
            embed=link.embed,
            start=link.start,
            end=link.end,
        )
        replacements.append((link.start, link.end, rewritten.text))
    if not replacements:
        return text, 0
    out: list[str] = []
    cursor = 0
    for start, end, value in replacements:
        out.append(text[cursor:start])
        out.append(value)
        cursor = end
    out.append(text[cursor:])
    return "".join(out), len(replacements)
