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

#: The image this helper knows how to retag — the one the shipped
#: ``v3/deploy/docker-compose.yml`` pins (see that file). A compose file
#: pinning a different image is left untouched (see
#: :func:`rewrite_compose_channel`'s docstring).
DEFAULT_IMAGE = "ghcr.io/byte5ai/palaia-hub"

_TAG_PATTERN = re.compile(r"(?P<prefix>image:\s*)(?P<image>[^\s:]+):(?P<tag>[\w.\-]+)")


def rewrite_compose_channel(
    text: str, channel: str, *, image: str = DEFAULT_IMAGE
) -> tuple[str, bool]:
    """Rewrite every ``image: <image>:<tag>`` line for ``image`` to pin
    ``channel`` as the tag instead. Every other line — comments, other
    services, unrelated images — passes through unchanged.

    Returns ``(new_text, changed)``; ``changed`` is ``False`` when no
    matching line needed editing (already on this channel, or the file
    pins a different image entirely — nothing to silently rewrite).
    """
    changed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group("image") != image:
            return match.group(0)
        if match.group("tag") != channel:
            changed = True
        return f"{match.group('prefix')}{match.group('image')}:{channel}"

    new_text = _TAG_PATTERN.sub(_replace, text)
    return new_text, changed


__all__ = ["DEFAULT_IMAGE", "rewrite_compose_channel"]
