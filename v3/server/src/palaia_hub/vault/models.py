"""Value types shared by the vault engine, watcher, git layer and doctor."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

#: The vault format version this engine writes (docs/vault-format.md v1.0).
VAULT_FORMAT_VERSION = 1

#: Engine-private, gitignored, rebuildable storage inside a vault (§1).
ENGINE_DIR = ".palaia"

#: The vault manifest (§1.2).
MANIFEST_PATH = "meta/vault.md"

#: Reserved top-level directories with defined semantics (§1).
RESERVED_DIRS: tuple[str, ...] = ("meta", "inbox", "review")

#: Directories the engine never treats as vault content.
IGNORED_DIRS: frozenset[str] = frozenset({".git", ENGINE_DIR, ".obsidian", ".trash"})

NOTE_SUFFIX = ".md"


@dataclass(frozen=True, slots=True)
class Attribution:
    """Who caused a write — the commit's ``agent/client/origin`` identity.

    ``human=True`` marks changes the engine did not make (external editor
    edits picked up on the next engine activity, format spec §10).
    """

    agent: str | None = None
    client: str | None = None
    provider: str | None = None
    session: str | None = None
    human: bool = False

    @property
    def origin(self) -> str:
        """The origin component of the commit subject."""
        if self.human:
            return "human"
        return self.provider or "engine"

    @property
    def prefix(self) -> str:
        """``agent/client/origin`` with ``-`` for unknown components."""
        agent = git_safe(self.agent or "") or "-"
        client = git_safe(self.client or "") or "-"
        return f"{agent}/{client}/{git_safe(self.origin) or '-'}"

    def subject(self, summary: str) -> str:
        """Build the commit subject: ``agent/client/origin: summary``."""
        return f"{self.prefix}: {summary}"

    def frontmatter_origin(self) -> dict[str, Any]:
        """Render the ``origin`` frontmatter map (§2.1)."""
        if self.human:
            return {"human": True}
        origin: dict[str, Any] = {}
        if self.provider:
            origin["provider"] = self.provider
        if self.client:
            origin["client"] = self.client
        if self.session:
            origin["session"] = self.session
        if self.agent:
            origin["agent"] = self.agent
        return origin

    def git_author(self) -> tuple[str, str]:
        """Return the ``(name, email)`` used as the commit author.

        The identity strings come from the connected client (issue #333):
        control characters and angle brackets are stripped, because git
        rejects an author name containing them and the write would then
        reach disk without its commit.
        """
        if self.human:
            return "human", "human@palaia.local"
        name = git_safe(self.agent or self.client or self.provider or "") or "palaia-hub"
        local = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-") or "palaia-hub"
        return name, f"{local}@palaia.local"


_GIT_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>]")


def git_safe(value: str) -> str:
    """``value`` with everything git refuses in an identity or trailer removed.

    Newlines would otherwise turn one caller-supplied field into extra commit
    trailers (or a failed commit); ``<`` and ``>`` delimit the author email.
    """
    return " ".join(_GIT_UNSAFE.sub(" ", value).split())


#: Default attribution for engine-initiated writes with no caller identity.
ENGINE = Attribution()

#: Attribution for changes made outside the engine (external editors).
HUMAN = Attribution(human=True)

TRAILER_PREFIX = "Palaia-"

Operation = Literal["init", "write", "edit", "move", "delete", "rename", "external", "index"]


def build_commit_message(
    attribution: Attribution,
    summary: str,
    *,
    operation: Operation,
    permalinks: Sequence[str] = (),
) -> str:
    """Build an attributed commit message: subject plus ``Palaia-*`` trailers."""
    lines = [attribution.subject(summary), ""]
    lines.append(f"{TRAILER_PREFIX}Operation: {operation}")
    for permalink in permalinks:
        lines.append(f"{TRAILER_PREFIX}Permalink: {permalink}")
    if attribution.human:
        lines.append(f"{TRAILER_PREFIX}Origin: human")
    for key, value in (
        ("Agent", attribution.agent),
        ("Client", attribution.client),
        ("Provider", attribution.provider),
        ("Session", attribution.session),
    ):
        if value:
            lines.append(f"{TRAILER_PREFIX}{key}: {git_safe(value)}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class Note:
    """A note as it exists on disk right now (raw, unparsed body)."""

    path: str
    permalink: str | None
    title: str
    frontmatter: Mapping[str, Any]
    body: str
    text: str
    checksum: str
    aliases: tuple[str, ...] = ()
    malformed_frontmatter: bool = False
    #: The file's bytes were not valid UTF-8 and ``text``/``body`` carry
    #: U+FFFD where they could not be decoded (issue #355). Read-only: the
    #: engine refuses to write such a note back.
    undecodable: bool = False


@dataclass(frozen=True, slots=True)
class WriteResult:
    """The outcome of a mutating engine call."""

    note: Note | None
    commit: str | None
    created: bool = False
    operation: Operation = "write"


@dataclass(frozen=True, slots=True)
class RenameResult:
    """The outcome of :meth:`VaultEngine.rename_entity`."""

    note: Note
    commit: str | None
    old_title: str
    old_permalink: str | None
    rewritten: Mapping[str, int] = field(default_factory=dict)

    @property
    def rewritten_links(self) -> int:
        """Total number of inbound wikilinks rewritten."""
        return sum(self.rewritten.values())


@dataclass(frozen=True, slots=True)
class DirEntry:
    """One entry of :meth:`VaultEngine.list_dir`."""

    path: str
    kind: Literal["dir", "note", "file"]
    permalink: str | None = None
    title: str | None = None
    size: int | None = None


@dataclass(frozen=True, slots=True)
class CommitInfo:
    """One commit from the vault's git history."""

    sha: str
    subject: str
    author_name: str
    author_email: str
    committed_at: datetime
    trailers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VaultInfo:
    """A vault's identity as declared by its manifest (§1.2)."""

    name: str
    path: str
    purpose: str | None = None
    format_version: int = VAULT_FORMAT_VERSION
    writable: bool = True
    note_count: int = 0
