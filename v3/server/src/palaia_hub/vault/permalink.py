"""Permalinks, slugs and the writer-side volatility rule.

Format spec §3.1: permalinks are ``[a-z0-9-]`` segments joined by ``/``,
mirroring the folder path at creation time, unique per vault, and **never**
changed by a file move or file rename — only an explicit identity rename
(§4.2) mints a new one.

Format spec §4.1 layers volatility enforcement: the *writer* rejects new
titles/permalinks carrying volatile tokens, the doctor flags existing ones,
the parser only warns. This module implements the writer's token patterns —
semver-like tokens, ISO dates, ``vX.Y`` forms — and nothing beyond them
(conceptual volatility needs semantics and is not a writer concern).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Container

PERMALINK_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_TRANSLITERATIONS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "æ": "ae",
    "ø": "oe",
    "å": "aa",
}

# Volatility token patterns (format spec §4.1, conformance cases 34-38).
_VOLATILE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iso-date", re.compile(r"(?<!\d)\d{4}-\d{2}(?:-\d{2})?(?!\d)")),
    ("version-tag", re.compile(r"(?i)(?<![a-z0-9])v\d+(?:[.-]\d+)+(?![a-z0-9])")),
    ("semver-like", re.compile(r"(?<![\d.])\d+\.\d+(?:\.\d+)*(?![\d.])")),
)


def slugify(text: str) -> str:
    """Return ``text`` as a single permalink segment (``[a-z0-9-]``)."""
    lowered = text.strip().lower()
    for source, replacement in _TRANSLITERATIONS.items():
        lowered = lowered.replace(source, replacement)
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def is_canonical(permalink: str) -> bool:
    """True when ``permalink`` matches the charset/segment rules of §3.1."""
    if not permalink or permalink.startswith("/") or permalink.endswith("/"):
        return False
    return all(PERMALINK_SEGMENT_RE.match(segment) for segment in permalink.split("/"))


def folder_prefix(relative_path: str) -> str:
    """Return the slugified folder prefix of a vault-relative note path."""
    parts = [part for part in relative_path.split("/")[:-1] if part]
    slugs = [slug for slug in (slugify(part) for part in parts) if slug]
    return "/".join(slugs)


def mint(relative_path: str, title: str) -> str:
    """Mint a permalink for a note at ``relative_path`` titled ``title``.

    The title's slug is prefixed with the note's folder path, per §3.1. A
    title that slugifies to nothing falls back to the filename stem.
    """
    stem = relative_path.rsplit("/", 1)[-1]
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    slug = slugify(title) or slugify(stem) or "note"
    prefix = folder_prefix(relative_path)
    return f"{prefix}/{slug}" if prefix else slug


def make_unique(candidate: str, taken: Container[str]) -> str:
    """Return ``candidate`` or the first free ``-2``, ``-3``, … variant."""
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in taken:
        suffix += 1
    return f"{candidate}-{suffix}"


def volatility_violations(text: str) -> list[str]:
    """Return the names of volatility patterns ``text`` matches (§4.1)."""
    return [name for name, pattern in _VOLATILE_PATTERNS if pattern.search(text)]


def describe_violations(kind: str, value: str, violations: list[str]) -> str:
    """Build the writer's rejection message for a volatile name."""
    joined = ", ".join(violations)
    return (
        f"{kind} {value!r} carries volatile data ({joined}). Format spec §4.1: "
        f"versions, dates and statuses belong in observations, not in names. "
        f"Fix: use a stable {kind} and record the volatile value as an "
        f"observation line, e.g. '- [version] 2026.5.7'."
    )
