"""Templating (SPEC-307 deliverable #3): ``{{event}}``, ``{{vault}}``,
``{{data.<key>}}`` substitution into action payloads.

A sandboxed substitution, not a template *language* — the same posture as
:mod:`.conditions`. ``render()`` never fails: a template referencing a
missing key substitutes empty and logs once per call (never once per
character, never once per byte of the queue), and delivery is never
blocked by a bad template.

"Escaped per sink" (the SPEC's wording): every current sink — a vault note
body, a stash JSON value, a notification's plain-text title/body — takes a
plain string with no markup layer of its own, so there is nothing to escape
beyond what each sink's own writer (YAML/JSON dump, Markdown body) already
does downstream. A future sink that renders raw HTML would need its own
escaping added here at that time.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..events.schema import Envelope

logger = logging.getLogger("palaia_hub.automations.templates")

#: ``{{event}}``, ``{{vault}}``, ``{{origin}}``, or ``{{data.<key>}}`` —
#: exactly the fields the condition grammar (§automations) also recognizes,
#: so a caller learns one small vocabulary for both.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(event|origin|vault|permalink|data\.[A-Za-z0-9_.]+)\s*\}\}")


def _lookup(name: str, envelope: Envelope) -> str | None:
    if name == "event":
        return envelope.event
    if name == "origin":
        return envelope.origin
    if name == "vault":
        return envelope.vault
    if name == "permalink":
        return envelope.permalink
    key = name[len("data.") :]
    if key not in envelope.data:
        return None
    value = envelope.data[key]
    return _stringify(value)


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def render(template: str, envelope: Envelope) -> str:
    """Substitute every ``{{...}}`` placeholder in ``template``.

    A missing key renders as empty string and is logged once for this
    ``render()`` call (not once per occurrence in the template, and never
    raised) — deliverable #3's "never fails delivery".
    """
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = _lookup(name, envelope)
        if value is None:
            missing.append(name)
            return ""
        return value

    rendered = _PLACEHOLDER_RE.sub(_sub, template)
    if missing:
        logger.warning(
            "automation template referenced missing field(s) %s for event %r; "
            "rendered empty",
            sorted(set(missing)),
            envelope.event,
        )
    return rendered


__all__ = ["render"]
