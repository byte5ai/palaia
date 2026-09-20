"""Backup **targets** (issue #297): where a hub writes its own archive.

SPEC-604 built the floor — one archive
(:mod:`palaia_hub.backup`), downloadable by a signed-in owner or written by
hand with ``palaia-hub backup``. Both paths need a person: a browser session
or a shell. The owner decision behind issue #297 is that backup has to work
without one, into a destination the operator names once.

**The abstraction, and what it is for.** Issue #297 designs three
destinations — a local directory, a user-defined external target, and a
per-vault ``git push`` — that differ in one way that actually matters, and
it is not their transport:

* a **full archive** carries ``config.yaml``, every token, the OAuth signing
  key and the upstream secret store *together with its encryption key*. It
  can act as the hub.
* a **vault** carries notes only. No hub secret has ever lived in one.

So the rule the issue states ("never pushed to a git remote or any target
the operator hasn't explicitly designated as secret-safe") is expressed here
as a class-level invariant every target declares and
:meth:`BackupTarget.run` enforces before a byte is produced:
:attr:`~BackupTarget.carries_full_archive` implies
:attr:`~BackupTarget.secret_safe`. A future notes-only git target sets the
first to ``False`` and needs no exemption; a future "ship the archive
somewhere" target cannot be written without answering the question. A target
class that gets it wrong fails :func:`run` on its first call rather than
after it has already put the hub's keys on a remote — see
``server/tests/backup/test_targets.py``.

**What is implemented here: the local directory** — the one the issue says
"must always work". The same bytes ``GET /api/backup`` streams, written
through a ``.part`` sibling that is renamed into place only once the archive
is complete (so a hub killed mid-write never leaves a truncated file under a
name that looks finished), at mode ``0600``, followed by retention over this
hub's *own* archives in that directory and nothing else.

**Not implemented here, on purpose:** the user-defined external target, the
per-vault git remote, and a scheduler. They are named in the config's own
validation error (:class:`palaia_hub.config.LocalDirectoryBackupTarget`) so
an operator who writes one is told it does not exist yet, instead of getting
a config that validates and never produces a backup.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from .backup import BackupError, archive_filename, iter_archive_bytes
from .config import BackupSettings, LocalDirectoryBackupTarget
from .events.schema import HubEventHook
from .security.files import FILE_MODE

logger = logging.getLogger("palaia_hub.backup_targets")

#: The glob that matches an archive :func:`palaia_hub.backup.archive_filename`
#: produced — and nothing else in the directory. Retention deletes only what
#: matches this: an operator's target directory is *theirs*, and a backup
#: feature that removes files it did not write is a data-loss bug waiting for
#: the first operator who points two things at one folder.
ARCHIVE_GLOB = "palaia-backup-*.tar.gz"

#: Appended while an archive is still being written. Deliberately outside
#: :data:`ARCHIVE_GLOB`, so a half-written file is never a retention
#: candidate and never looks like a restorable archive.
PARTIAL_SUFFIX = ".part"

#: Issue #297: "failures surface as events/notifications, never silently."
SUCCEEDED_EVENT = "backup.target.succeeded"
FAILED_EVENT = "backup.target.failed"
EVENT_ORIGIN = "backup"


class BackupTargetError(RuntimeError):
    """A target could not be built, or could not complete a run.

    The message names the target and, where a path is involved, the path —
    never file contents, same rule as :class:`palaia_hub.backup.BackupError`.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class BackupRun:
    """What one completed run of one target did."""

    target: str
    kind: str
    destination: str
    #: The archive this run produced, as the target names it (a filename for
    #: a directory target).
    artifact: str
    bytes_written: int
    #: Older archives retention deleted, oldest first.
    pruned: tuple[str, ...]
    duration_seconds: float

    def to_json(self) -> dict[str, Any]:
        """The ``data`` of a ``backup.target.succeeded`` event, and the REST
        response body. Carries no path outside the target's own destination
        and nothing about the archive's contents."""
        return {
            "target": self.target,
            "kind": self.kind,
            "destination": self.destination,
            "artifact": self.artifact,
            "bytes_written": self.bytes_written,
            "pruned": list(self.pruned),
            "duration_seconds": round(self.duration_seconds, 3),
        }


class BackupTarget(ABC):
    """One destination this hub can write a backup to.

    Subclasses declare two facts about *what they move* and implement one
    method that moves it. See the module docstring for why those two facts
    are class-level rather than configurable per instance: they are
    properties of the transport, not of the operator's taste, and making
    them configurable would make the guard below opt-out.
    """

    #: The ``type:`` an operator writes in ``config.yaml``.
    kind: ClassVar[str]
    #: Does this target move the full hub archive (secret store *and* key)?
    carries_full_archive: ClassVar[bool]
    #: Is this destination one the archive's key material may reach at all?
    secret_safe: ClassVar[bool]

    def __init__(self, *, name: str) -> None:
        self.name = name

    @property
    @abstractmethod
    def destination(self) -> str:
        """Where this target writes, for logs, events and the REST list."""

    def describe(self) -> dict[str, Any]:
        """This target as the REST surface and the CLI show it."""
        return {
            "name": self.name,
            "kind": self.kind,
            "destination": self.destination,
            "carries_full_archive": self.carries_full_archive,
            "secret_safe": self.secret_safe,
        }

    def run(self, home: Path) -> BackupRun:
        """Back ``home`` up to this target, once.

        Enforces issue #297's secret-safety rule first — before any archive
        is built, so a misdeclared target cannot leak on the way to failing.
        """
        if self.carries_full_archive and not self.secret_safe:
            raise BackupTargetError(
                f"backup target {self.name!r} ({self.kind}) would move the full archive — "
                f"which contains this hub's tokens, its OAuth signing key and the secret "
                f"store together with the key it is encrypted under — to a destination "
                f"that is not marked secret-safe. Refused."
            )
        started = time.monotonic()
        artifact, written, pruned = self._write(home)
        return BackupRun(
            target=self.name,
            kind=self.kind,
            destination=self.destination,
            artifact=artifact,
            bytes_written=written,
            pruned=pruned,
            duration_seconds=time.monotonic() - started,
        )

    @abstractmethod
    def _write(self, home: Path) -> tuple[str, int, tuple[str, ...]]:
        """Do the transfer. Returns ``(artifact, bytes_written, pruned)``."""


class LocalDirectoryTarget(BackupTarget):
    """A directory on this machine (or a mounted share) — issue #297 #1.

    Carries the full archive, and is secret-safe: it is a path on the
    operator's own filesystem, chosen by the operator, which is exactly
    where ``palaia-hub backup`` has always written the identical bytes. What
    the hub can still enforce — and does, per run — is that the destination
    is not *inside* the hub home it archives.
    """

    kind = "local_directory"
    carries_full_archive = True
    secret_safe = True

    def __init__(self, *, name: str, directory: Path, keep_last: int | None) -> None:
        super().__init__(name=name)
        self.directory = directory
        self.keep_last = keep_last

    @property
    def destination(self) -> str:
        return str(self.directory)

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "keep_last": self.keep_last}

    def _write(self, home: Path) -> tuple[str, int, tuple[str, ...]]:
        self._refuse_inside_home(home)
        target = self.directory / archive_filename()
        partial = target.with_name(target.name + PARTIAL_SUFFIX)
        written = 0
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as handle:
                for chunk in iter_archive_bytes(home):
                    handle.write(chunk)
                    written += len(chunk)
            # 0600 before the rename, never after: between the two there
            # would be a window where a finished-looking archive of every
            # key this hub holds sits at whatever the umask allowed.
            partial.chmod(FILE_MODE)
            partial.replace(target)
        except (OSError, BackupError) as exc:
            # A partial file left behind would be dead weight in a directory
            # retention deliberately does not touch, so clean it up — but
            # never at the cost of replacing the real error with this one.
            try:
                partial.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - the unlink of a file we just made
                logger.warning("could not remove the partial archive %s", partial)
            raise BackupTargetError(
                f"backup target {self.name!r} could not write into {self.directory}: {exc}"
            ) from exc
        return target.name, written, self.prune()

    def _refuse_inside_home(self, home: Path) -> None:
        """A hub must not back itself up into itself.

        Each run would archive every archive before it, so the second backup
        is twice the size of the first and the tenth is unusable — and a
        "backup" that only ever exists inside the directory it protects
        survives none of the failures a backup is for.
        """
        resolved_home = home.resolve()
        resolved_directory = self.directory.resolve()
        if resolved_directory.is_relative_to(resolved_home):
            raise BackupTargetError(
                f"backup target {self.name!r} points at {self.directory}, which is inside "
                f"the hub's own data directory ({home}). Each backup would then contain "
                f"every backup before it, and none of them would survive losing that "
                f"directory. Fix: point `path` somewhere else — an external drive, a "
                f"mounted share, another volume."
            )

    def prune(self) -> tuple[str, ...]:
        """Delete this target's oldest archives beyond ``keep_last``.

        Only files matching :data:`ARCHIVE_GLOB` are ever considered, and
        they sort by name: :func:`palaia_hub.backup.archive_filename` stamps
        them ``…-YYYYMMDDTHHMMSSZ.tar.gz``, where lexicographic order *is*
        chronological order (fixed width, zero-padded, UTC) — so this never
        has to trust an mtime that a copy or a restore may have rewritten.

        A file that cannot be deleted is logged and skipped: retention is
        housekeeping, and a read-only share must not turn a backup that
        succeeded into a run that reports failure.
        """
        if self.keep_last is None:
            return ()
        try:
            archives = sorted(path for path in self.directory.glob(ARCHIVE_GLOB) if path.is_file())
        except OSError as exc:  # pragma: no cover - the directory we just wrote into
            logger.warning("could not list %s for retention: %s", self.directory, exc)
            return ()
        pruned: list[str] = []
        for path in archives[: max(0, len(archives) - self.keep_last)]:
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("could not delete the old archive %s: %s", path, exc)
                continue
            pruned.append(path.name)
        return tuple(pruned)


def build_target(settings: LocalDirectoryBackupTarget) -> BackupTarget:
    """Build one configured target."""
    return LocalDirectoryTarget(
        name=settings.name,
        directory=Path(settings.path).expanduser(),
        keep_last=settings.keep_last,
    )


def build_targets(settings: BackupSettings) -> dict[str, BackupTarget]:
    """Every configured target, by name (empty when none are configured).

    Names are unique by construction — :class:`palaia_hub.config.
    BackupSettings` refuses a duplicate rather than letting one target
    silently shadow another in this mapping.
    """
    return {target.name: build_target(target) for target in settings.targets}


def run_target(
    target: BackupTarget, home: Path, *, publish: HubEventHook | None = None
) -> BackupRun:
    """Run one target and report the outcome on the event bus.

    Issue #297: *"failures surface as events/notifications, never
    silently."* Both outcomes are published — a failure carries the reason
    in plain language — and the exception is re-raised either way, so the
    caller (REST route, CLI) still decides what to do about it. Publishing
    itself never masks the run's own result: an event bus that raises here
    would otherwise turn a completed backup into a reported failure.
    """
    try:
        run = target.run(home)
    except Exception as exc:
        _publish(
            publish,
            FAILED_EVENT,
            {
                "target": target.name,
                "kind": target.kind,
                "destination": target.destination,
                "reason": str(exc),
            },
        )
        raise
    _publish(publish, SUCCEEDED_EVENT, run.to_json())
    return run


def _publish(publish: HubEventHook | None, event: str, data: dict[str, Any]) -> None:
    if publish is None:
        return
    try:
        publish(event, data)
    except Exception:  # noqa: BLE001 - see run_target's docstring
        logger.exception("could not publish %s for backup target %r", event, data.get("target"))


__all__ = [
    "ARCHIVE_GLOB",
    "EVENT_ORIGIN",
    "FAILED_EVENT",
    "PARTIAL_SUFFIX",
    "SUCCEEDED_EVENT",
    "BackupRun",
    "BackupTarget",
    "BackupTargetError",
    "LocalDirectoryTarget",
    "build_target",
    "build_targets",
    "run_target",
]
