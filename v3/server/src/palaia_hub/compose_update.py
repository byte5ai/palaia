"""``palaia-hub update``'s file-editing half (SPEC-501 deliverable #4).

Inside a container, "self-update" is pull-and-recreate — something a
container cannot portably do to itself. For a compose deployment, this
module does the one part that *can* be automated (switching the pinned
image tag to a different channel in the operator's own
``docker-compose.yml``) and stops there; the recreate itself is always two
commands the operator runs, printed by :mod:`palaia_hub.cli`, never run on
their behalf.
"""

from __future__ import annotations

import re
from typing import Literal

#: The image this helper knows how to retag — the one the shipped
#: ``v3/deploy/docker-compose.yml`` pins (see that file). A compose file
#: pinning a different image is left untouched (see
#: :func:`rewrite_compose_channel`'s docstring).
DEFAULT_IMAGE = "ghcr.io/byte5ai/palaia-hub"

#: What :func:`rewrite_compose_channel` found (issue #371): the tag was
#: switched, the file already pinned the channel, or no line pins the image
#: at all — three different things the CLI must say three different ways.
RewriteOutcome = Literal["changed", "already", "not_found"]

# An ``image:`` value, bare or quoted (``image: "ghcr.io/…:stable"`` is how
# many people write it — issue #371); the closing quote must match the
# opening one.
_TAG_PATTERN = re.compile(
    r"(?P<prefix>image:\s*)(?P<quote>[\"']?)(?P<image>[^\s:\"']+):(?P<tag>[\w.\-]+)(?P=quote)"
)


def rewrite_compose_channel(
    text: str, channel: str, *, image: str = DEFAULT_IMAGE
) -> tuple[str, RewriteOutcome]:
    """Rewrite every ``image: <image>:<tag>`` line for ``image`` to pin
    ``channel`` as the tag instead. Every other line — comments, other
    services, unrelated images — passes through unchanged.

    Returns ``(new_text, outcome)``: ``"changed"`` when at least one line
    was retagged, ``"already"`` when every matching line pinned ``channel``
    already, and ``"not_found"`` when no line pins ``image`` at all (a
    mirror registry, a different image) — the case the CLI used to report
    as "already on the channel" while the file stayed as it was.
    """
    changed = False
    matched = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed, matched
        if match.group("image") != image:
            return match.group(0)
        matched = True
        if match.group("tag") != channel:
            changed = True
        quote = match.group("quote")
        return f"{match.group('prefix')}{quote}{match.group('image')}:{channel}{quote}"

    new_text = _TAG_PATTERN.sub(_replace, text)
    if changed:
        return new_text, "changed"
    return text, "already" if matched else "not_found"


__all__ = ["DEFAULT_IMAGE", "RewriteOutcome", "rewrite_compose_channel"]
