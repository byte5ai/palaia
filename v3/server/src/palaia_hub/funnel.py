"""SPEC-504 deliverable #3: local-only first-run funnel instrumentation.

MASTERPLAN §13's success metric is time-to-first-memory (install -> first
entry), and §10's privacy principle is "no data leaves the host unless the
user connects something that reads it." This module is where those two
promises meet: it records the timestamps behind that metric, and it never
does anything a request could carry off-box.

**Local-only, by construction, not by policy** — this module imports no
HTTP client, opens no socket, and makes no outbound call of any kind. The
only I/O it performs is reading and writing one JSON file
(``funnel_stats.json``) under the hub's own home directory, through the
same atomic-write primitive :mod:`palaia_hub.modes.audit` uses for the mode
audit log. ``server/tests/funnel/test_no_egress.py`` proves this by
patching ``socket.socket`` to raise and driving the whole funnel path (hub
boot, vault creation, a client connecting, a first memory write) through
it without a failure — there is no code path here that could reach for a
socket even if a bug tried to.

**What "install" means here**: nothing inside the hub process can observe
the actual `docker run`/`docker compose up` moment (that happens before
any palaia code runs at all), so this module uses the hub's own first-ever
boot as the practical proxy for "install" — :meth:`FunnelStore.record_hub_
started` only ever sets ``hub_started_at`` once, the very first time a hub
runs against a given home directory; every later restart is a no-op. That
matches MASTERPLAN §13's own framing ("install -> first entry") more
closely than timing from the wizard's first HTTP request would: a wizard
that sits open in a forgotten browser tab for an hour must not inflate the
number, and it does not, because the clock started at boot, not at click.

**Event-driven, not client-timestamped**: every timestamp here is set from
a real hub-side event (:mod:`palaia_hub.events.bus`) the moment the
underlying thing actually happened server-side — never from a timestamp a
browser tab sends over the wire. A wizard tab left open, backgrounded, or
revisited cannot skew this number, and neither can a client that lies
about when it thinks something happened.

**Known funnel-audit finding, documented rather than fixed here** (SPEC-504
deliverable #2's "document each change honestly; larger redesigns become
filed issues, not scope creep"): the wizard's "start from a template"
switch (``CreateVaultRequest.template`` in :mod:`palaia_hub.dashboard_api`)
writes its two seed notes through the same code path a real capture does,
so each one is itself a ``memory.entry.created`` event. A wizard run with
that switch on records a near-zero time-to-first-memory — the seed note,
not the client's own first write. That switch defaults to *off*
(``Onboarding.tsx``), so this does not affect the common path, but making
"first memory" mean "first memory a *client* wrote" rather than "first
note that exists" would need the vault engine to carry attribution through
to the public event (nothing in :mod:`palaia_hub.vault.events` does today)
— real, but more than this SPEC's instrumentation deliverable, so it is
named here rather than silently absorbed into a bigger change.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import palaia_home
from .events.bus import EventBus
from .events.schema import Envelope
from .vault.atomic import atomic_write_text

STATS_FILE = "funnel_stats.json"


def format_duration(seconds: float) -> str:
    """Render an elapsed duration the way the dashboard shows it: ``"4m12s"``.

    Deliberately terse (no "hours, minutes and seconds" prose) — this is a
    tile label, read at a glance next to "Vaults" and "Clients", not a
    sentence. Seconds are always shown once the total drops under an hour
    so "37s" and "4m12s" both read as exact, not rounded.
    """
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


@dataclass(frozen=True, slots=True)
class FunnelStatus:
    """The dashboard hub-status surface's whole view of the funnel."""

    hub_started_at: float | None
    vault_created_at: float | None
    client_connected_at: float | None
    first_memory_at: float | None

    @property
    def time_to_first_memory_seconds(self) -> float | None:
        """``None`` until both ends of the measurement exist."""
        if self.hub_started_at is None or self.first_memory_at is None:
            return None
        return max(0.0, self.first_memory_at - self.hub_started_at)

    @property
    def time_to_first_memory_display(self) -> str | None:
        seconds = self.time_to_first_memory_seconds
        return None if seconds is None else format_duration(seconds)


class FunnelStore:
    """Reads and writes ``funnel_stats.json`` under the hub's home directory.

    Same shape of contract as :class:`palaia_hub.modes.audit.ModeAuditLog`:
    one small JSON file, atomic writes, no database. Every ``record_*``
    method is first-write-wins — calling it again after a value is already
    set is a no-op, both because a restart must not reset the funnel's
    start line and because "first client connected"/"first memory" are, by
    definition, about the *first* occurrence.
    """

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else palaia_home()
        self.path = self.home / STATS_FILE

    def _load(self) -> dict[str, float | None]:
        if not self.path.exists():
            return {
                "hub_started_at": None,
                "vault_created_at": None,
                "client_connected_at": None,
                "first_memory_at": None,
            }
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "hub_started_at": raw.get("hub_started_at"),
            "vault_created_at": raw.get("vault_created_at"),
            "client_connected_at": raw.get("client_connected_at"),
            "first_memory_at": raw.get("first_memory_at"),
        }

    def _save(self, data: dict[str, float | None]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(data))

    def _record_once(self, key: str, ts: float | None) -> None:
        data = self._load()
        if data[key] is not None:
            return
        data[key] = ts if ts is not None else time.time()
        self._save(data)

    def record_hub_started(self, ts: float | None = None) -> None:
        self._record_once("hub_started_at", ts)

    def record_vault_created(self, ts: float | None = None) -> None:
        self._record_once("vault_created_at", ts)

    def record_client_connected(self, ts: float | None = None) -> None:
        self._record_once("client_connected_at", ts)

    def record_first_memory(self, ts: float | None = None) -> None:
        self._record_once("first_memory_at", ts)

    def status(self) -> FunnelStatus:
        data = self._load()
        return FunnelStatus(
            hub_started_at=data["hub_started_at"],
            vault_created_at=data["vault_created_at"],
            client_connected_at=data["client_connected_at"],
            first_memory_at=data["first_memory_at"],
        )


def wire_funnel_tracking(event_bus: EventBus, store: FunnelStore) -> Callable[[], None]:
    """Subscribe ``store`` to the four events the funnel cares about.

    Same posture as the hooks/automations dispatchers in
    :mod:`palaia_hub.app`: a plain in-process bus consumer that the bus
    itself knows nothing special about. Returns the unsubscribe callable
    :meth:`~palaia_hub.events.bus.EventBus.on` hands back.
    """

    def _on_event(envelope: Envelope) -> None:
        if envelope.event == "hub.started":
            store.record_hub_started(envelope.ts)
        elif envelope.event == "memory.vault.created":
            store.record_vault_created(envelope.ts)
        elif envelope.event == "client.connected":
            store.record_client_connected(envelope.ts)
        elif envelope.event == "memory.entry.created":
            store.record_first_memory(envelope.ts)

    return event_bus.on(_on_event)


__all__ = [
    "STATS_FILE",
    "FunnelStatus",
    "FunnelStore",
    "format_duration",
    "wire_funnel_tracking",
]
