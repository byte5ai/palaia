"""Surgically patch ``config.yaml`` (SPEC-205 deliverable #1).

The hub's ``config.yaml`` is meant to be hand-edited (see
:data:`palaia_hub.config.DEFAULT_CONFIG_TEMPLATE`'s own comments) — a
dashboard-driven mode change must not silently delete every comment the
operator or the default template wrote. :mod:`yaml` has no round-trip mode
that preserves comments (that's ``ruamel.yaml``, not a dependency here), so
this module edits the file as text instead: find the line for each
requested key (top-level, or one level under an existing section header)
and replace only its value, leaving every other line — including every
comment — byte-for-byte untouched. A key with no existing line is appended
(to the file for a top-level key, to the end of its section for a nested
one, creating the section if it does not exist yet).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from ..config import harden_config_file
from ..vault.atomic import atomic_write_text


def _format_scalar(value: Any) -> str:
    """Render ``value`` as the exact text that goes after ``key:``.

    Dumped as ``{"v": value}`` rather than ``value`` alone: PyYAML appends
    a ``\\n...\\n`` document-end marker when a bare scalar is the *whole*
    document, which a plain ``.strip()`` cannot cleanly remove — wrapping
    it in a one-key mapping avoids that entirely and, as a side effect,
    quotes a string exactly the way ``yaml.safe_load`` needs it quoted to
    read back as that same string (e.g. ``'yes'``, ``'123'``, ``'a: b'``).
    """
    dumped = yaml.safe_dump({"v": value}, default_flow_style=False).strip()
    return dumped.removeprefix("v:").strip()


def _top_level_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)


def _section_header_pattern(section: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(section)}:[ \t]*(#.*)?$", re.MULTILINE)


def _nested_key_pattern(key: str) -> re.Pattern[str]:
    return re.compile(rf"^(  {re.escape(key)}:).*$", re.MULTILINE)


def _patch_top_level(text: str, updates: dict[str, Any]) -> str:
    for key, value in updates.items():
        rendered = f"{key}: {_format_scalar(value)}"
        pattern = _top_level_pattern(key)
        if pattern.search(text):
            text = pattern.sub(rendered, text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += f"{rendered}\n"
    return text


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    """Return ``(header_end, section_end)`` byte offsets, or ``None``.

    ``section_end`` is where the next top-level (unindented, non-comment,
    non-blank) line starts, or ``len(text)`` — i.e. the end of every line
    that belongs to this section (its own comments and nested keys).
    """
    header = _section_header_pattern(section).search(text)
    if header is None:
        return None
    cursor = header.end() + 1 if header.end() < len(text) else header.end()
    end = len(text)
    for match in re.finditer(r"^\S.*$", text[cursor:], re.MULTILINE):
        end = cursor + match.start()
        break
    return cursor, end


def _patch_nested_section(text: str, section: str, updates: dict[str, Any]) -> str:
    span = _section_span(text, section)
    if span is None:
        # No such section yet: append a fresh one at the end of the file.
        if text and not text.endswith("\n"):
            text += "\n"
        body = "\n".join(f"  {key}: {_format_scalar(value)}" for key, value in updates.items())
        return text + f"{section}:\n{body}\n"

    start, end = span
    body = text[start:end]
    remaining = dict(updates)
    for key in list(remaining):
        pattern = _nested_key_pattern(key)
        if pattern.search(body):
            body = pattern.sub(f"  {key}: {_format_scalar(remaining.pop(key))}", body, count=1)
    if remaining:
        addition = "".join(
            f"  {key}: {_format_scalar(value)}\n" for key, value in remaining.items()
        )
        if body and not body.endswith("\n"):
            body += "\n"
        body += addition
    return text[:start] + body + text[end:]


def replace_config_section(path: Path, section: str, rendered_body: str) -> None:
    """Replace a whole top-level section's body, preserving every other
    line — including every comment outside that section — untouched.

    Unlike :func:`patch_config_values` (one flat scalar key at a time),
    this is for a section whose *value* is itself structured (SPEC-301's
    ``gateway:`` list of profile/vault objects): PyYAML has no comment-
    preserving way to patch inside a list, so the whole section is
    round-tripped as one block instead. ``rendered_body`` is that block's
    already-rendered text — every line indented, one trailing newline — the
    same shape :func:`_patch_nested_section` above builds by hand for a
    flat mapping; a caller with a structured value (e.g.
    :func:`palaia_hub.gateway.settings_bridge.render_gateway_section`)
    renders it via ``yaml.safe_dump`` instead.

    A ``section:`` header with no existing body is added if the section is
    entirely absent; an existing section's body (everything indented under
    its header, comments included) is replaced outright — a section this
    function writes is expected to be edited only through the API that
    calls it, not by hand, so no attempt is made to preserve comments
    *inside* it, only around it.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    span = _section_span(text, section)
    if span is None:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{section}:\n{rendered_body}"
    else:
        start, end = span
        text = text[:start] + rendered_body + text[end:]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    harden_config_file(path)


def patch_config_values(path: Path, updates: dict[str, Any]) -> None:
    """Rewrite ``path`` with ``updates`` applied, preserving everything else.

    ``updates`` keys are dotted for a one-level-nested setting (e.g.
    ``"oauth.issuer"``, ``"exposure.public_url"``) and bare for a top-level
    one (``"mode"``, ``"host"``, ``"auth_enabled"``). Deeper nesting is not
    supported — no setting this SPEC writes needs it.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""

    top_level: dict[str, Any] = {}
    nested: dict[str, dict[str, Any]] = {}
    for dotted, value in updates.items():
        if "." in dotted:
            section, key = dotted.split(".", 1)
            nested.setdefault(section, {})[key] = value
        else:
            top_level[dotted] = value

    text = _patch_top_level(text, top_level)
    for section, section_updates in nested.items():
        text = _patch_nested_section(text, section, section_updates)

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    harden_config_file(path)


__all__ = ["patch_config_values", "replace_config_section"]
