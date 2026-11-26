"""Who is calling: the connected AI app behind the current memory tool call.

A write that reaches a vault through the gateway used to be committed as the
engine's own ("palaia"), so a note's history and the dashboard's activity
feed could not say which app saved it. The gateway's vault services ask
:func:`client_attribution` for the caller on every write: the access key the
request carried names the app ("Claude Code CLI", "Codex").
"""

from __future__ import annotations

from collections.abc import Callable

from fastmcp.server.dependencies import get_access_token

from ..vault import Attribution
from .store import TokenError, TokenStore

#: Returns the caller of the tool call in progress, or ``None`` when there is
#: none to name (no request, no access key, a key the store does not know).
AttributionSource = Callable[[], Attribution | None]


def client_attribution(store: TokenStore | None) -> AttributionSource:
    """An :data:`AttributionSource` that names the app by its access key."""

    def current() -> Attribution | None:
        if store is None:
            return None
        token = get_access_token()
        if token is None:
            return None
        try:
            info = store.get(token.client_id)
        except TokenError:
            # A connection that signed in with the owner's account has no
            # access key of its own, so there is no app name to give.
            return None
        return Attribution(client=info.name)

    return current


__all__ = ["AttributionSource", "client_attribution"]
