"""Per-vault **git push** (issue #438): a vault's notes into a git repository
the owner names, for example a private GitHub repository.

Every vault is already a git repository (:mod:`palaia_hub.vault.gitlayer`).
Pushing it somewhere else is a copy of the notes off this machine, with their
full history. It is the one backup destination that is *not* the full
archive: a vault holds notes only, and no hub secret has ever lived in one
(``docs/backup-restore.md`` §5.1). So, unlike a backup folder, it may go to a
third-party host.

**Configured in the dashboard, not in ``config.yaml``.** The push needs a
credential, and credentials live in the encrypted secret store
(:mod:`palaia_hub.upstream.secrets`), never in plain text. What is not
secret (repository URL, branch, user name, how the last push went) is kept
in ``vault-remotes.json`` in the hub home, next to the other stores. Both
travel inside the full archive like everything else there.

**The vault repository itself is never reconfigured.** The push goes to the
URL directly (``git push <url> HEAD:refs/heads/<branch>``); no ``git remote``
is added, so nothing changes for a user who also opens the vault in
Obsidian and its git plugin.

**The token never reaches argv, a log or a response.** It is handed to the
one ``git push`` process through ``GIT_CONFIG_COUNT``/``GIT_CONFIG_KEY_n``
environment variables as an ``Authorization`` header scoped to the
repository's own host, so a redirect to another host never carries it. Any
text git prints is scrubbed of the token (and its encoded form) before it is
logged, published or returned.

**HTTPS only.** The hub image has no SSH client, and an ``http://`` URL would
send the token in clear text. Both are refused when the push is configured,
as is a URL with a user name or password in it: the credential goes in the
token field, where it is stored encrypted.

**Never forced.** When the remote branch has commits this vault does not
have, the push is rejected and the reason says so. A backup that silently
overwrote someone's repository would be the opposite of a backup.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .events.schema import HubEventHook
from .security.files import FILE_MODE, enforce_private_mode
from .upstream.secrets import SecretStore
from .vault.atomic import atomic_write_text

logger = logging.getLogger("palaia_hub.vault_remote")

#: The non-secret half of every configured push, in the hub home.
REMOTES_FILENAME = "vault-remotes.json"
#: The token for vault ``<key>`` is the secret ``vault-remote.<key>``.
SECRET_PREFIX = "vault-remote."
#: The user name sent with the token when the owner gives none. GitHub
#: accepts any user name with a personal access token; this is the one its
#: own documentation uses for tokens.
DEFAULT_USERNAME = "x-access-token"
DEFAULT_BRANCH = "main"
#: One push must not hold a worker thread forever on a hung network.
PUSH_TIMEOUT_SECONDS = 300.0
#: How much of git's own error text a failure reason keeps.
_REASON_LIMIT = 600

PUSHED_EVENT = "backup.vault_remote.pushed"
FAILED_EVENT = "backup.vault_remote.failed"

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,99}$")


class VaultRemoteError(RuntimeError):
    """A push could not be configured or carried out. Never contains a token."""


class VaultRemoteBusyError(VaultRemoteError):
    """This vault is already being pushed (by the schedule or an earlier click)."""


@dataclasses.dataclass(frozen=True, slots=True)
class PushRecord:
    """How one push went — what the dashboard shows and the status file keeps."""

    ok: bool
    trigger: str
    finished_at: float
    #: The commit that was pushed (the vault's HEAD), on success.
    commit: str | None = None
    #: Plain-language reason, on failure. Scrubbed of every credential.
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, raw: object) -> PushRecord | None:
        if not isinstance(raw, Mapping):
            return None
        try:
            return cls(
                ok=bool(raw["ok"]),
                trigger=str(raw["trigger"]),
                finished_at=float(raw["finished_at"]),
                commit=None if raw.get("commit") is None else str(raw["commit"]),
                reason=None if raw.get("reason") is None else str(raw["reason"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclasses.dataclass(frozen=True, slots=True)
class VaultRemote:
    """Where one vault is pushed to. The token is not part of it."""

    vault: str
    url: str
    branch: str = DEFAULT_BRANCH
    username: str = DEFAULT_USERNAME


def secret_name(vault: str) -> str:
    """The secret-store name holding the token for ``vault``."""
    return f"{SECRET_PREFIX}{vault}"


def validate_url(url: str) -> str:
    """Accept an ``https://host/path`` repository URL and nothing else."""
    value = url.strip()
    parts = urlsplit(value)
    if parts.scheme != "https":
        raise VaultRemoteError(
            f"repository URL {value!r} must start with https://. palaia pushes over HTTPS "
            "only: plain http would send the token unencrypted, and the hub has no SSH "
            "client. Fix: use the repository's HTTPS address, e.g. "
            "https://github.com/you/notes.git."
        )
    if not parts.hostname:
        raise VaultRemoteError(f"repository URL {value!r} has no host name.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise VaultRemoteError(
            "the repository URL contains a user name or password. Fix: remove it from the "
            "URL and put the access token in the token field, where it is stored encrypted."
        )
    if parts.query or parts.fragment:
        raise VaultRemoteError(
            f"repository URL {value!r} has a query or fragment. Fix: use the plain "
            "repository address."
        )
    if parts.path in ("", "/"):
        raise VaultRemoteError(
            f"repository URL {value!r} names a host but no repository. Fix: add the "
            "repository path, e.g. https://github.com/you/notes.git."
        )
    return value


def validate_branch(branch: str) -> str:
    value = branch.strip()
    if (
        not _BRANCH_RE.match(value)
        or ".." in value
        or value.endswith((".lock", "/", "."))
        or "//" in value
    ):
        raise VaultRemoteError(
            f"branch name {value!r} is not usable. Fix: use letters, digits and "
            "'.', '_', '-' or '/', for example 'main'."
        )
    return value


def validate_username(username: str) -> str:
    value = username.strip()
    if not _USERNAME_RE.match(value):
        raise VaultRemoteError(
            f"user name {value!r} is not usable. Fix: leave it empty (for GitHub) or use "
            "the account name your git host expects with a token."
        )
    return value


def _credential_env(remote: VaultRemote, token: str) -> dict[str, str]:
    """The environment that carries the token into one ``git push``.

    ``http.<scheme>://<host>/.extraHeader`` applies the header only to URLs
    on the repository's own host, so a redirect elsewhere never sees it.
    ``credential.helper`` is emptied so a helper configured on the machine
    can neither prompt nor store anything.
    """
    parts = urlsplit(remote.url)
    basic = base64.b64encode(f"{remote.username}:{token}".encode()).decode("ascii")
    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"http.{parts.scheme}://{parts.netloc}/.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
    }


def _scrub(text: str, remote: VaultRemote, token: str) -> str:
    """Remove every form of the credential from text git printed, and git's
    ``hint:`` lines, which only repeat advice for a person at a terminal."""
    basic = base64.b64encode(f"{remote.username}:{token}".encode()).decode("ascii")
    for secret in (basic, token):
        if secret:
            text = text.replace(secret, "***")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("hint:")]
    return " ".join(" ".join(lines).split())


def _explain(stderr: str) -> str:
    """Turn git's rejection into the reason an owner can act on."""
    lowered = stderr.lower()
    if (
        "non-fast-forward" in lowered
        or "fetch first" in lowered
        or "[rejected]" in lowered
        or "remote contains work" in lowered
    ):
        return (
            "the repository's branch has commits this vault does not have, so palaia did "
            "not overwrite it. Fix: push into an empty repository or a new branch name."
        )
    if (
        "authentication failed" in lowered
        or "403" in lowered
        or "401" in lowered
        or "could not read username" in lowered
    ):
        return (
            "the repository refused the credentials. Fix: check that the token is valid "
            "and allowed to write to this repository."
        )
    if "not found" in lowered or "404" in lowered:
        return (
            "the repository was not found. Fix: check the URL, and that the token can see "
            "the repository (private repositories answer 'not found' to a token without "
            "access)."
        )
    if "could not resolve host" in lowered or "failed to connect" in lowered:
        return "the repository's host could not be reached from this hub."
    return "git push failed"


class VaultRemotes:
    """Every configured vault push, their tokens, and how each last went.

    Args:
        home: the hub home; ``vault-remotes.json`` lives there.
        secrets: the hub's encrypted secret store — where the tokens go.
        vault_roots: returns the registered vaults as ``{key: root}``. Read
            on every call, so a vault added after start-up can be configured
            without a restart.
        publish: the event hook each push reports on. Failures are never
            silent (issue #297).
    """

    def __init__(
        self,
        home: Path,
        secrets: SecretStore,
        vault_roots: Callable[[], Mapping[str, Path]],
        *,
        publish: HubEventHook | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = Path(home) / REMOTES_FILENAME
        self._secrets = secrets
        self._vault_roots = vault_roots
        self._publish = publish
        self._clock = clock
        self._lock = threading.Lock()
        self._pushing: set[str] = set()
        self._remotes: dict[str, VaultRemote] = {}
        self._last: dict[str, PushRecord] = {}
        self._load()

    # ------------------------------------------------------------- reading

    def get(self, vault: str) -> VaultRemote | None:
        with self._lock:
            return self._remotes.get(vault)

    def configured(self) -> list[str]:
        with self._lock:
            return sorted(self._remotes)

    def describe(self) -> list[dict[str, Any]]:
        """Every registered vault, with its push if one is configured.

        Never the token — only whether one is stored.
        """
        roots = self._vault_roots()
        with self._lock:
            names = sorted(set(roots) | set(self._remotes))
            listed: list[dict[str, Any]] = []
            for name in names:
                remote = self._remotes.get(name)
                last = self._last.get(name)
                listed.append(
                    {
                        "vault": name,
                        "registered": name in roots,
                        "remote": None
                        if remote is None
                        else {
                            "url": remote.url,
                            "branch": remote.branch,
                            "username": remote.username,
                            "has_token": self._secrets.has(secret_name(name)),
                        },
                        "pushing": name in self._pushing,
                        "last_push": None if last is None else last.to_json(),
                    }
                )
        return listed

    # ------------------------------------------------------------- writing

    def configure(
        self,
        vault: str,
        *,
        url: str,
        branch: str | None = None,
        username: str | None = None,
        token: str | None = None,
    ) -> VaultRemote:
        """Set (or change) where ``vault`` is pushed.

        ``token`` may be left out when changing a push that already has one,
        so the owner can edit the URL without re-entering it.
        """
        if vault not in self._vault_roots():
            raise VaultRemoteError(f"there is no vault named {vault!r} on this hub.")
        remote = VaultRemote(
            vault=vault,
            url=validate_url(url),
            branch=validate_branch(branch or DEFAULT_BRANCH),
            username=validate_username(username or DEFAULT_USERNAME),
        )
        token = (token or "").strip()
        if not token and not self._secrets.has(secret_name(vault)):
            raise VaultRemoteError(
                "an access token is needed to push. Fix: create a token that may write to "
                "this repository and paste it into the token field."
            )
        if token:
            self._secrets.put(secret_name(vault), token)
        with self._lock:
            previous = self._remotes.get(vault)
            self._remotes[vault] = remote
            if previous is not None and (previous.url, previous.branch) != (
                remote.url,
                remote.branch,
            ):
                # The last outcome was about another destination.
                self._last.pop(vault, None)
            self._save_locked()
        logger.info("vault %r now pushes to %s (branch %s)", vault, remote.url, remote.branch)
        return remote

    def remove(self, vault: str) -> bool:
        """Stop pushing ``vault``: forget the destination and delete its token."""
        with self._lock:
            existed = self._remotes.pop(vault, None) is not None
            self._last.pop(vault, None)
            self._save_locked()
        deleted = self._secrets.delete(secret_name(vault))
        return existed or deleted

    # ------------------------------------------------------------- pushing

    def push(self, vault: str, *, trigger: str) -> PushRecord:
        """Push ``vault`` once. Blocking — call it from a worker thread.

        Raises :class:`VaultRemoteBusyError` when this vault is already
        being pushed, and :class:`VaultRemoteError` with the reason when the
        push failed (the failure is recorded and published first).
        """
        with self._lock:
            remote = self._remotes.get(vault)
            if remote is None:
                raise VaultRemoteError(f"vault {vault!r} has no git repository to push to.")
            if vault in self._pushing:
                raise VaultRemoteBusyError(
                    f"vault {vault!r} is already being pushed. It will show up here "
                    "when it is done."
                )
            self._pushing.add(vault)
        try:
            try:
                commit = self._push(remote)
            except VaultRemoteError as exc:
                record = PushRecord(
                    ok=False, trigger=trigger, finished_at=self._clock(), reason=str(exc)
                )
                self._finish(vault, record)
                self._emit(
                    FAILED_EVENT,
                    {
                        "vault": vault,
                        "url": remote.url,
                        "branch": remote.branch,
                        "reason": str(exc),
                        "trigger": trigger,
                    },
                )
                raise
            record = PushRecord(ok=True, trigger=trigger, finished_at=self._clock(), commit=commit)
            self._finish(vault, record)
            self._emit(
                PUSHED_EVENT,
                {
                    "vault": vault,
                    "url": remote.url,
                    "branch": remote.branch,
                    "commit": commit,
                    "trigger": trigger,
                },
            )
            return record
        finally:
            with self._lock:
                self._pushing.discard(vault)

    def push_all(self, *, trigger: str) -> dict[str, bool]:
        """Push every configured vault, continuing past a failure.

        Returns ``{vault: ok}``; a vault skipped because it was busy is not
        in it.
        """
        outcome: dict[str, bool] = {}
        for vault in self.configured():
            try:
                self.push(vault, trigger=trigger)
            except VaultRemoteBusyError:
                continue
            except VaultRemoteError as exc:
                logger.warning("vault push of %r failed: %s", vault, exc)
                outcome[vault] = False
                continue
            outcome[vault] = True
        return outcome

    def _push(self, remote: VaultRemote) -> str:
        root = self._vault_roots().get(remote.vault)
        if root is None:
            raise VaultRemoteError(f"vault {remote.vault!r} is no longer registered on this hub.")
        if not (root / ".git").exists():
            raise VaultRemoteError(f"vault {remote.vault!r} has no git history to push yet.")
        token = self._secrets.get(secret_name(remote.vault))
        if not token:
            raise VaultRemoteError(
                f"no access token is stored for vault {remote.vault!r}. Fix: enter one in "
                "the dashboard's Backups screen."
            )
        env = {**os.environ, **_credential_env(remote, token)}
        head = self._git(root, ["rev-parse", "HEAD"], env=env, timeout=30.0)
        if head.returncode != 0:
            raise VaultRemoteError(f"vault {remote.vault!r} has no commit to push yet.")
        commit = head.stdout.strip()
        try:
            result = self._git(
                root,
                ["push", "--porcelain", remote.url, f"HEAD:refs/heads/{remote.branch}"],
                env=env,
                timeout=PUSH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise VaultRemoteError(
                f"pushing vault {remote.vault!r} took longer than "
                f"{int(PUSH_TIMEOUT_SECONDS)} seconds and was stopped."
            ) from exc
        if result.returncode != 0:
            detail = _scrub(f"{result.stderr}\n{result.stdout}", remote, token)
            raise VaultRemoteError(f"{_explain(detail)} (git: {detail[:_REASON_LIMIT]})")
        return commit

    @staticmethod
    def _git(
        root: Path, args: list[str], *, env: dict[str, str], timeout: float
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VaultRemoteError("git is not installed on the machine palaia runs on.") from exc

    # ------------------------------------------------------------ bookkeeping

    def _finish(self, vault: str, record: PushRecord) -> None:
        with self._lock:
            if vault in self._remotes:
                self._last[vault] = record
                self._save_locked()

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._publish is None:
            return
        try:
            self._publish(event, data)
        except Exception:  # noqa: BLE001 - publishing never masks the push's own result
            logger.exception("could not publish %s for vault %r", event, data.get("vault"))

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            enforce_private_mode(self._path, FILE_MODE)
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "%s could not be read (%s); no vault push is configured until it is fixed "
                "or set again in the dashboard",
                self._path,
                exc,
            )
            return
        entries = raw.get("vaults") if isinstance(raw, Mapping) else None
        if not isinstance(entries, Mapping):
            return
        for vault, entry in entries.items():
            if not isinstance(entry, Mapping):
                continue
            try:
                remote = VaultRemote(
                    vault=str(vault),
                    url=validate_url(str(entry["url"])),
                    branch=validate_branch(str(entry.get("branch") or DEFAULT_BRANCH)),
                    username=validate_username(str(entry.get("username") or DEFAULT_USERNAME)),
                )
            except (KeyError, VaultRemoteError) as exc:
                logger.warning("ignoring the push configured for vault %r: %s", vault, exc)
                continue
            self._remotes[remote.vault] = remote
            record = PushRecord.from_json(entry.get("last_push"))
            if record is not None:
                self._last[remote.vault] = record

    def _save_locked(self) -> None:
        payload = {
            "vaults": {
                name: {
                    "url": remote.url,
                    "branch": remote.branch,
                    "username": remote.username,
                    "last_push": None if name not in self._last else self._last[name].to_json(),
                }
                for name, remote in sorted(self._remotes.items())
            }
        }
        atomic_write_text(self._path, json.dumps(payload, indent=2) + "\n")
        enforce_private_mode(self._path, FILE_MODE)


__all__ = [
    "DEFAULT_BRANCH",
    "DEFAULT_USERNAME",
    "FAILED_EVENT",
    "PUSHED_EVENT",
    "REMOTES_FILENAME",
    "SECRET_PREFIX",
    "PushRecord",
    "VaultRemote",
    "VaultRemoteBusyError",
    "VaultRemoteError",
    "VaultRemotes",
    "secret_name",
    "validate_branch",
    "validate_url",
    "validate_username",
]
