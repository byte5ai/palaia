"""Detection plus rate-awareness: the part that decides what actually rides
along on a result (issue #301).

Detection alone would repeat the same sentence on every call — a search
against a degraded index is degraded on call one and on call fifty. The
issue's constraint is explicit: *the same nudge does not repeat on every
call, and total guidance stays small, because agent context windows are the
budget.* This module is where that constraint lives.

The policy, in three parts:

1. **Per-session cooldown.** A nudge's ``(key, state)`` identity stays quiet
   for :data:`~palaia_hub.nudges.models.DEFAULT_COOLDOWN_SECONDS` after it
   fires in that session. A detector that sets a coarse ``state`` gets to
   speak again when the condition materially changes (a backlog crossing into
   the next bucket); one that does not is strictly once per cooldown.
2. **Per-result cap.** At most
   :data:`~palaia_hub.nudges.models.MAX_NUDGES_PER_RESULT` nudges on one
   result, no matter how many detectors fired.
3. **Bounded memory.** The limiter remembers sessions and identities in
   LRU order and evicts, so a long-lived hub with many short sessions cannot
   grow this table without limit. Eviction only ever *re-allows* a nudge; it
   never suppresses one, so the failure mode is "said once more than strictly
   necessary", not "stayed silent when it mattered".

Sessions are identified by a caller-supplied callable rather than by reaching
into the transport from here — the MCP one lives in
:mod:`palaia_hub.gateway.guidance`, and a CLI or dashboard caller supplies
its own. Keeping it injected is also what makes the rate policy testable with
a fake clock and no server at all.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from .detectors import DETECTORS, Detector, detect
from .models import DEFAULT_COOLDOWN_SECONDS, MAX_NUDGES_PER_RESULT, Nudge, VaultSignals

#: Session key used when the caller cannot identify a session (a direct
#: in-process call, a transport without sessions). Rate limiting then applies
#: hub-wide rather than per session — the conservative direction: fewer
#: repeats, never more.
ANONYMOUS_SESSION = "-"

_DEFAULT_MAX_SESSIONS = 256
_DEFAULT_MAX_IDENTITIES_PER_SESSION = 64


class NudgeEngine:
    """Runs the detectors, then applies the rate policy. Not thread-safe by
    design — one engine belongs to one vault's tool server, and MCP tool
    bodies for a server run on a single event loop.

    ``session_key`` is called once per :meth:`emit`; it must never raise (the
    gateway's implementation swallows a missing transport context and returns
    :data:`ANONYMOUS_SESSION`). ``clock`` is a monotonic seconds source,
    injected so the cooldown is testable without sleeping.
    """

    def __init__(
        self,
        *,
        detectors: tuple[Detector, ...] = DETECTORS,
        session_key: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        max_per_result: int = MAX_NUDGES_PER_RESULT,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
        max_identities_per_session: int = _DEFAULT_MAX_IDENTITIES_PER_SESSION,
    ) -> None:
        self._detectors = detectors
        self._session_key = session_key or (lambda: ANONYMOUS_SESSION)
        self._clock = clock
        self._cooldown = cooldown_seconds
        self._max_per_result = max_per_result
        self._max_sessions = max_sessions
        self._max_identities = max_identities_per_session
        #: session key -> (nudge identity -> when it last fired), both in LRU
        #: order so eviction takes the least recently touched entry.
        self._fired: OrderedDict[str, OrderedDict[tuple[str, str], float]] = OrderedDict()

    def emit(self, signals: VaultSignals) -> list[Nudge]:
        """The guidance this result should carry — possibly, and usually, none.

        Calling this records the returned nudges as fired, so it is not a
        query: call it once per result, and attach what it gives back.
        """
        candidates = detect(signals, self._detectors)
        if not candidates:
            return []
        seen = self._session_table(self._session_key())
        now = self._clock()
        allowed: list[Nudge] = []
        for nudge in candidates:
            if len(allowed) >= self._max_per_result:
                break
            last = seen.get(nudge.identity)
            if last is not None and now - last < self._cooldown:
                seen.move_to_end(nudge.identity)
                continue
            seen[nudge.identity] = now
            seen.move_to_end(nudge.identity)
            allowed.append(nudge)
        self._evict(seen)
        return allowed

    def _session_table(self, session: str) -> OrderedDict[tuple[str, str], float]:
        table = self._fired.get(session)
        if table is None:
            table = OrderedDict()
            self._fired[session] = table
        self._fired.move_to_end(session)
        while len(self._fired) > self._max_sessions:
            self._fired.popitem(last=False)
        return table

    def _evict(self, table: OrderedDict[tuple[str, str], float]) -> None:
        while len(table) > self._max_identities:
            table.popitem(last=False)


__all__ = ["ANONYMOUS_SESSION", "NudgeEngine"]
