"""The mode-change audit log (SPEC-205 deliverable #1).

Every attempted mode/exposure change — accepted or refused — gets one
append-only JSON line in ``mode_audit.jsonl`` under the hub's home
directory. A security-relevant, network-posture-changing action must be
reviewable after the fact even when the attempt was refused (a refused
attempt is itself a signal worth keeping — someone tried to open this hub
up and could not).

Kept deliberately simple: a flat JSONL file, not a database — this is a
low-volume, append-mostly log (nobody changes operating mode often), and a
plain file is trivially `tail`-able and greppable.

Each entry is one ``O_APPEND`` write of one line, under a process-wide lock
(issue #347). The earlier read-whole-file-and-rewrite made every append
O(size of the log) and let two concurrent mode changes lose each other's
line — for a security audit trail the lost line is the part that matters.
An appending write of a single line is atomic on every local filesystem
this hub runs on, and the file is created owner-only.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..config import palaia_home
from ..security.files import harden_file

AUDIT_FILE = "mode_audit.jsonl"


@dataclass(frozen=True, slots=True)
class ModeAuditEntry:
    """One line of the mode-change audit trail."""

    from_mode: str
    to_mode: str
    accepted: bool
    #: Empty when accepted; the actionable refusal message otherwise.
    reason: str
    #: The dotted setting names the request touched (``mode``, ``host``,
    #: ``oauth.issuer``, ``exposure.public_url``, ...) — not the raw
    #: values, since a value here could carry a secret path or token in a
    #: future field even though none of today's mode/exposure settings do.
    changed_keys: tuple[str, ...]
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "ts": self.ts,
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "accepted": self.accepted,
            "reason": self.reason,
            "changed_keys": list(self.changed_keys),
        }


class ModeAuditLog:
    """Appends to, and reads back, ``mode_audit.jsonl``."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else palaia_home()
        self.path = self.home / AUDIT_FILE
        self._lock = threading.Lock()

    def record(
        self,
        *,
        from_mode: str,
        to_mode: str,
        accepted: bool,
        reason: str = "",
        changed_keys: tuple[str, ...] = (),
    ) -> ModeAuditEntry:
        entry = ModeAuditEntry(
            from_mode=from_mode,
            to_mode=to_mode,
            accepted=accepted,
            reason=reason,
            changed_keys=changed_keys,
        )
        line = (json.dumps(entry.to_json()) + "\n").encode("utf-8")
        self.home.mkdir(parents=True, exist_ok=True)
        with self._lock:
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                view = memoryview(line)
                while view:
                    written = os.write(fd, view)
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            harden_file(self.path)
        return entry

    def recent(self, limit: int = 50) -> list[dict[str, object]]:
        """Return up to ``limit`` most-recent entries, newest first."""
        if not self.path.exists():
            return []
        raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        lines = [line for line in raw_lines if line.strip()]
        entries = [json.loads(line) for line in lines[-limit:]]
        entries.reverse()
        return entries


__all__ = ["AUDIT_FILE", "ModeAuditEntry", "ModeAuditLog"]
