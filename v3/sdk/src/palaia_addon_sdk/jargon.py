"""The one jargon blocklist, extracted so the SDK and the hub's SPEC-207
skill lint can both import it rather than keeping two copies that drift.

This is a verbatim move of the rules from
``server/tests/clients/skill_lint.py`` (SPEC-207 deliverable #2's "no
jargon in user-facing text") — the SDK now owns the canonical copy (it
must be importable with zero dependency on ``palaia_hub``), and the
server's skill lint imports it back (see that module's docstring). Same
words, same stripping rules, same behavior either side of that import.
"""

from __future__ import annotations

import re

#: Words that mean something inside this repository and nothing to someone
#: reading an add-on's manifest or a skill in their own agent. Checked
#: against user-facing prose only — never against code, tool names, or
#: identifiers.
JARGON: tuple[str, ...] = (
    "mcp",
    "vault",
    "permalink",
    "frontmatter",
    "namespace",
    "inbox",
    "curator",
    "curate",
    "idempotent",
    "wikilink",
    "observation",
    "provenance",
    "dedup",
    "dedups",
    "deduplicate",
    "schema",
    "spec-",
    "adr",
    "token budget",
    "knowledge graph",
)

_FENCE_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*$", re.MULTILINE)


def strip_code(text: str) -> str:
    """Drop fenced blocks, inline code and table rows.

    Those are where tool names and field identifiers live
    (``work_memory_capture``, ``config_schema``), and an identifier is not
    jargon — it is the string someone has to type.
    """
    without_fences = _FENCE_RE.sub("", text)
    without_tables = _TABLE_ROW_RE.sub("", without_fences)
    return _INLINE_CODE_RE.sub("", without_tables)


def find_jargon(text: str) -> list[str]:
    """Blocklisted words present in ``text``, in blocklist order, deduplicated."""
    haystack = strip_code(text).lower()
    hits: list[str] = []
    for word in JARGON:
        pattern = (
            rf"\b{re.escape(word)}"
            if word.endswith("-")
            else rf"\b{re.escape(word)}(?:s|es|ed|ing)?\b"
        )
        if re.search(pattern, haystack) and word not in hits:
            hits.append(word)
    return hits


__all__ = ["JARGON", "find_jargon", "strip_code"]
