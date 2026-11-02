"""Where a curator write or edit would really land (issue #603).

The curator guards (:mod:`palaia_hub.curator.policy`) protect ``inbox/`` and
``review/``. Judging the raw tool argument is not enough: the vault resolves
a reference by permalink, alias, title or path suffix, and normalizes a
folder like ``./inbox`` to ``inbox``. So the guard asks the vault itself
which note the call names — the same resolution the call will use — and
the middleware then hands the call on addressed by exactly that note, so
the note that was checked is the note that changes.
"""

from __future__ import annotations

import asyncio
import posixpath
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..gateway.wiring import note_path_for, tag_list
from ..vault import AmbiguousReferenceError, InvalidPathError, NoteNotFoundError, VaultEngine
from .policy import MutationTarget, folder_argument

#: The folder argument and its aliases, as the memory tools absorb them.
_FOLDER_ALIASES: tuple[str, ...] = ("dir", "path")


@dataclass(frozen=True, slots=True)
class ResolvedCall:
    """A write or edit as the vault resolves it.

    Attributes:
        target: what the guard judges.
        arguments: the call's arguments, addressed canonically (the edit's
            ``permalink`` set to the resolved note, the write's ``folder`` set
            to the normalized folder), or ``None`` when nothing resolved and
            the call goes on unchanged to fail with the vault's own error.
    """

    target: MutationTarget
    arguments: dict[str, Any] | None


class MutationTargets(Protocol):
    """Resolves one vault's write/edit calls for the curator guard."""

    async def resolve(self, action: str, arguments: Mapping[str, Any]) -> ResolvedCall: ...


class EngineMutationTargets:
    """:class:`MutationTargets` over a real :class:`~palaia_hub.vault.VaultEngine`."""

    def __init__(self, engine: VaultEngine) -> None:
        self._engine = engine

    async def resolve(self, action: str, arguments: Mapping[str, Any]) -> ResolvedCall:
        if action == "write":
            return self._resolve_write(arguments)
        if action == "edit":
            return await self._resolve_edit(arguments)
        return ResolvedCall(target=MutationTarget(path=None), arguments=None)

    def _resolve_write(self, arguments: Mapping[str, Any]) -> ResolvedCall:
        title = arguments.get("title")
        if not isinstance(title, str):
            return ResolvedCall(target=MutationTarget(path=None), arguments=None)
        try:
            path = self._engine.normalize_path(note_path_for(title, folder_argument(arguments)))
        except InvalidPathError:
            return ResolvedCall(target=MutationTarget(path=None), arguments=None)
        rewritten = {k: v for k, v in arguments.items() if k not in _FOLDER_ALIASES}
        rewritten["folder"] = posixpath.dirname(path)
        return ResolvedCall(target=MutationTarget(path=path), arguments=rewritten)

    async def _resolve_edit(self, arguments: Mapping[str, Any]) -> ResolvedCall:
        reference = arguments.get("permalink")
        if not isinstance(reference, str):
            return ResolvedCall(target=MutationTarget(path=None), arguments=None)
        try:
            entry = self._engine.resolve(reference)
        except (NoteNotFoundError, AmbiguousReferenceError):
            return ResolvedCall(target=MutationTarget(path=None), arguments=None)
        note = await asyncio.to_thread(self._engine.read_note_at, entry.path)
        tags = tuple(tag_list(note.frontmatter.get("tags")))
        rewritten = dict(arguments)
        rewritten["permalink"] = entry.permalink or entry.path
        return ResolvedCall(target=MutationTarget(path=entry.path, tags=tags), arguments=rewritten)


__all__ = ["EngineMutationTargets", "MutationTargets", "ResolvedCall"]
