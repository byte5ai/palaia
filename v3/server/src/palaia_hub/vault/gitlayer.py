"""Git layer for a vault: attributed auto-commits, changed-paths staging, gc.

**Backend choice — porcelain ``git`` via subprocess.** SPEC-003 measured both
options (findings Q3). libgit2/pygit2 commits faster per call, but it has no
maintenance story at all: one-commit-per-write bloated ``.git`` to 1.16 GiB
for ~10 MiB of content at 10k notes (~116x, O(n²) loose objects), while the
same workload through porcelain ``git`` stayed at 142 MiB because git's own
``gc.auto`` housekeeping fired transparently. pygit2 would additionally need
the ``git`` binary anyway (libgit2 exposes no gc), so this layer uses the
binary for everything and keeps its latency flat by never rescanning the
whole tree.

Two bindings from those findings are implemented here:

1. **Stage only changed paths.** Never ``git add -A`` over the whole tree:
   per-commit cost otherwise grows with vault size (pygit2 add-all went
   9.2 ms → 78.5 ms from 1k → 10k notes).
2. **An explicit gc policy.** ``gc.auto`` is set far below git's 6,700 default
   at init, and the layer runs ``git gc --auto`` itself every
   ``gc_commit_interval`` commits — plus :meth:`GitRepo.gc` for the doctor's
   scheduled maintenance. A full ``git gc`` recovered 10.9x in the spike.

It also owns **stale lock recovery**: a ``kill -9`` mid-commit left a stale
``.git/index.lock`` in 2 of 25 spike trials, and removing it was always
sufficient repair. Recovery is routine startup work here, not an exception.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .errors import GitError
from .models import TRAILER_PREFIX, Attribution, CommitInfo

logger = logging.getLogger("palaia_hub.vault.git")

_UNIT = "\x1f"
_RECORD = "\x1e"

_LOG_FORMAT = _UNIT.join(["%H", "%an", "%ae", "%aI", "%s", "%b"]) + _RECORD

_COMMITTER_NAME = "palaia-hub"
_COMMITTER_EMAIL = "hub@palaia.local"

# Every way git says "there was nothing to record" (working tree clean,
# untracked files only, nothing staged).
_EMPTY_COMMIT_PHRASES = (
    "nothing to commit",
    "nothing added to commit",
    "no changes added to commit",
)

# `git commit` prints e.g. "[main (root-commit) 1a2b3c4] subject".
_COMMIT_SHA_RE = re.compile(r"^\[[^\]]*?\b([0-9a-f]{7,40})\]", re.MULTILINE)


def _parse_commit_sha(stdout: str) -> str | None:
    match = _COMMIT_SHA_RE.search(stdout)
    return match.group(1) if match else None


@dataclass(frozen=True, slots=True)
class GitPolicy:
    """The vault repository's housekeeping policy.

    Attributes:
        gc_auto: ``gc.auto`` written to the repo config. Git's default of
            6,700 loose objects is tuned for human commit rates; one commit
            per write reaches it far too late, so we repack much earlier.
        gc_auto_pack_limit: ``gc.autoPackLimit`` — consolidate packs early so
            incremental repacks do not accumulate hundreds of packfiles.
        gc_detach: ``gc.autoDetach`` — background auto-gc keeps the write path
            free of multi-second repack stalls (the spike saw 1.9 s outliers).
        gc_commit_interval: run ``git gc --auto`` explicitly every N commits.
        stale_lock_after: a ``*.lock`` file untouched for this many seconds is
            crash residue. Normal git operations hold index.lock for
            milliseconds, and the engine serializes its own git calls, so a
            lock this old belongs to a process that died.
    """

    gc_auto: int = 256
    gc_auto_pack_limit: int = 8
    gc_detach: bool = True
    gc_commit_interval: int = 500
    stale_lock_after: float = 5.0


DEFAULT_POLICY = GitPolicy()


@dataclass(frozen=True, slots=True)
class LockRecovery:
    """A lock file the layer found, and whether it removed it."""

    path: str
    age_seconds: float
    removed: bool


class GitRepo:
    """The vault's git repository — attributed commits and housekeeping.

    All methods are blocking; the engine calls them from a worker thread
    under the per-vault write lock, so a repository is only ever touched by
    one engine operation at a time.
    """

    def __init__(self, root: Path, policy: GitPolicy = DEFAULT_POLICY) -> None:
        self.root = root
        self.policy = policy
        self._commits_since_gc = 0

    # ---------------------------------------------------------------- plumbing

    def _run(
        self,
        args: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
        read_only: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = ["git", "-C", str(self.root), *args]
        # GIT_LITERAL_PATHSPECS: every path this layer passes is an exact
        # file name, never a pattern. Without it git reads a leading ':' as
        # pathspec magic even after `--` (`git add -A -- ':todo.md'` →
        # "did not match any files"), and one such file created in an
        # editor would fail the sweep at the start of every write (#334).
        full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1"}
        if read_only:
            # Keep read-only queries from taking the index lock at all.
            full_env["GIT_OPTIONAL_LOCKS"] = "0"
        if env:
            full_env.update(env)
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            env=full_env,
            check=False,
        )
        if check and result.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed in {self.root} "
                f"(exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    @property
    def git_dir(self) -> Path:
        """Path to the repository's ``.git`` directory."""
        return self.root / ".git"

    @property
    def initialized(self) -> bool:
        """True when the vault root is a git repository."""
        return self.git_dir.exists()

    # ------------------------------------------------------------------ set-up

    def init(self) -> bool:
        """Initialize the repository if needed; return True when created."""
        created = False
        if not self.initialized:
            self._run(["init", "--initial-branch=main", "--quiet"])
            created = True
            self._write_repo_defaults()
        self.apply_policy()
        return created

    def _write_repo_defaults(self) -> None:
        """Settings written **once**, when the engine creates the repository.

        Commit signing is turned off for the vault's own repository. A vault
        commits on every write, so an inherited global ``commit.gpgsign``
        would put an external signing program on the write path: it multiplies
        write latency and adds a failure mode outside the engine's control
        (observed while benchmarking this SPEC — a sandbox's signing helper ran
        out of file descriptors after ~5,500 commits and every subsequent
        vault write failed). Vault history is a local memory log, not a
        published artifact; a user who wants it signed can set
        ``commit.gpgsign true`` in the vault repository and the engine will
        respect it, since this is written only at creation time. Repositories
        the engine adopts are never reconfigured.
        """
        for key, value in (("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            self._run(["config", key, value])

    def apply_policy(self) -> None:
        """Write the housekeeping policy into the repository's own config.

        Stored in the repo (not passed per call) so the same limits apply to
        commits made by Obsidian's git plugin or by the user on the shell.
        """
        for key, value in (
            ("gc.auto", str(self.policy.gc_auto)),
            ("gc.autoPackLimit", str(self.policy.gc_auto_pack_limit)),
            ("gc.autoDetach", "true" if self.policy.gc_detach else "false"),
        ):
            self._run(["config", key, value])

    # --------------------------------------------------------- crash recovery

    def find_locks(self) -> list[Path]:
        """Return lock files present in ``.git`` (index, HEAD, refs, config)."""
        if not self.git_dir.exists():
            return []
        candidates = [
            self.git_dir / "index.lock",
            self.git_dir / "HEAD.lock",
            self.git_dir / "config.lock",
            self.git_dir / "shallow.lock",
        ]
        refs = self.git_dir / "refs"
        if refs.exists():
            candidates.extend(sorted(refs.rglob("*.lock")))
        return [path for path in candidates if path.exists()]

    def recover_stale_locks(self, *, stale_after: float | None = None) -> list[LockRecovery]:
        """Remove crash-residue git locks; report every lock that was found.

        A lock younger than the staleness threshold is reported but **not**
        removed — it may belong to a live external ``git`` process (an
        Obsidian git-plugin sync, a shell command), and deleting that would
        corrupt someone else's in-flight operation.
        """
        threshold = self.policy.stale_lock_after if stale_after is None else stale_after
        now = time.time()
        recoveries: list[LockRecovery] = []
        for lock in self.find_locks():
            try:
                age = now - lock.stat().st_mtime
            except OSError:  # pragma: no cover - vanished under us
                continue
            removed = False
            if age >= threshold:
                try:
                    lock.unlink()
                    removed = True
                except OSError:  # pragma: no cover - vanished under us
                    removed = False
                if removed:
                    logger.warning(
                        "removed stale git lock %s (age %.1fs) — crash recovery",
                        lock.name,
                        age,
                    )
            recoveries.append(LockRecovery(path=lock.name, age_seconds=age, removed=removed))
        return recoveries

    # ------------------------------------------------------------------ status

    def status(self) -> list[tuple[str, str]]:
        """Return ``(status_code, path)`` for every change git can see.

        Renames are reported as their target path; ignored files (``.palaia/``,
        engine temp files) never appear.
        """
        result = self._run(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            read_only=True,
        )
        return _parse_porcelain(result.stdout)

    def dirty_paths(self) -> list[str]:
        """Vault-relative paths with uncommitted changes."""
        return [path for _, path in self.status()]

    # ----------------------------------------------------------------- commits

    def commit_paths(
        self,
        paths: Iterable[str],
        message: str,
        attribution: Attribution,
        *,
        allow_empty: bool = False,
    ) -> str | None:
        """Stage exactly ``paths`` and commit them; return the commit sha.

        Returns ``None`` when nothing was staged (and ``allow_empty`` is
        false) — e.g. a rewrite that produced identical bytes.
        """
        pathspecs = [path for path in dict.fromkeys(paths) if path]
        if not pathspecs and not allow_empty:
            return None
        if pathspecs:
            # `-A` with a pathspec stages modifications, additions AND
            # deletions for those paths only — never a whole-tree rescan.
            self._run(["add", "-A", "--", *pathspecs])

        name, email = attribution.git_author()
        env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": _COMMITTER_NAME,
            "GIT_COMMITTER_EMAIL": _COMMITTER_EMAIL,
        }
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        # One process, not three: `commit` itself reports "nothing to commit"
        # (no separate `diff --cached` probe) and prints the new sha (no
        # separate `rev-parse`). Every spawn avoided is ~25-45 ms off the
        # write path, which is what keeps per-write latency flat.
        result = self._run(args, env=env, check=False)
        if result.returncode != 0:
            combined = f"{result.stdout}\n{result.stderr}"
            if any(phrase in combined for phrase in _EMPTY_COMMIT_PHRASES):
                return None
            raise GitError(
                f"git commit failed in {self.root} (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        self._commits_since_gc += 1
        self._maybe_gc()
        return _parse_commit_sha(result.stdout) or self.head()

    def head(self) -> str | None:
        """Return the current HEAD sha, or ``None`` on an unborn branch."""
        result = self._run(["rev-parse", "--verify", "HEAD"], check=False, read_only=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def log(self, path: str | None = None, *, limit: int = 50) -> list[CommitInfo]:
        """Return the history of the vault, or of one path (following moves)."""
        args = ["log", f"--max-count={limit}", f"--format={_LOG_FORMAT}"]
        if path is not None:
            args.extend(["--follow", "--", path])
        result = self._run(args, check=False, read_only=True)
        if result.returncode != 0:
            return []
        return _parse_log(result.stdout)

    def path_at_head(self, path: str) -> bool:
        """True when ``path`` is tracked in the current commit."""
        result = self._run(["cat-file", "-e", f"HEAD:{path}"], check=False, read_only=True)
        return result.returncode == 0

    # ------------------------------------------------------------ housekeeping

    def _maybe_gc(self) -> None:
        interval = self.policy.gc_commit_interval
        if interval <= 0 or self._commits_since_gc < interval:
            return
        self._commits_since_gc = 0
        self.gc(auto=True)

    def gc(self, *, auto: bool = False, aggressive: bool = False) -> None:
        """Run git housekeeping. ``auto=True`` is the cheap thresholded form."""
        args = ["gc", "--quiet"]
        if auto:
            args.append("--auto")
        if aggressive:
            args.append("--aggressive")
        result = self._run(args, check=False)
        if result.returncode != 0:  # pragma: no cover - gc is advisory
            logger.warning(
                "git gc in %s exited %s: %s", self.root, result.returncode, result.stderr.strip()
            )

    def size_bytes(self) -> int:
        """Total size of the ``.git`` directory in bytes."""
        return _dir_size(self.git_dir)

    def content_size_bytes(self) -> int:
        """Total size of the working tree excluding ``.git``."""
        total = 0
        for entry in self.root.rglob("*"):
            if ".git" in entry.parts:
                continue
            if entry.is_file():
                total += entry.stat().st_size
        return total


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:  # pragma: no cover - transient pack rename
                continue
    return total


def _parse_porcelain(raw: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    fields = [field for field in raw.split("\0") if field]
    index = 0
    while index < len(fields):
        field = fields[index]
        code, _, path = field[:2], field[2:3], field[3:]
        if code.startswith("R") or code.startswith("C"):
            # Rename/copy: this record's path is the target, the *next* field
            # is the source. Both are reported so callers can stage either.
            if index + 1 < len(fields):
                entries.append((code, fields[index + 1]))
                index += 1
        entries.append((code, path))
        index += 1
    return entries


def _parse_log(raw: str) -> list[CommitInfo]:
    commits: list[CommitInfo] = []
    for record in raw.split(_RECORD):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_UNIT)
        if len(parts) < 6:  # pragma: no cover - defensive
            continue
        sha, author_name, author_email, iso, subject, body = parts[:6]
        commits.append(
            CommitInfo(
                sha=sha,
                subject=subject,
                author_name=author_name,
                author_email=author_email,
                committed_at=datetime.fromisoformat(iso),
                trailers=_parse_trailers(body),
            )
        )
    return commits


def _parse_trailers(body: str) -> dict[str, str]:
    trailers: dict[str, str] = {}
    for line in body.splitlines():
        if not line.startswith(TRAILER_PREFIX) or ":" not in line:
            continue
        key, _, value = line.partition(":")
        name = key[len(TRAILER_PREFIX) :].strip().lower()
        existing = trailers.get(name)
        trailers[name] = f"{existing},{value.strip()}" if existing else value.strip()
    return trailers
