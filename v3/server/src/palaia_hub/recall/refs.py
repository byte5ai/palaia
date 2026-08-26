"""``memory://`` addressing — parsing and resolution (format spec §3.2).

The scheme is small but every one of its forms carries weight:

======================================== ====================================
``memory://<vault>/<permalink>``         fully qualified
``memory://<permalink>``                 the calling token's default vault
``memory://projects/api-*``              glob: ``*`` in a segment, ``**`` across
``memory://<permalink>#^<block-id>``     one addressable block (§5.4)
``memory://<permalink>/obs/<cat>/<h8>``  a synthetic observation permalink (§9.2)
``memory://<permalink>/rel/<t>/<target>``a synthetic relation permalink (§9.2)
======================================== ====================================

A bare string resolves in exactly one order — **exact permalink → alias →
exact title (case-insensitive) → unique path suffix** — and ambiguity at any
tier is an error that lists the candidates. That last part is the load-bearing
half: silently picking one of two notes called "Pricing" is how a memory
system starts quietly answering with the wrong note.

Synthetic sub-note permalinks are matched *before* the note tiers and by
exact equality, not by parsing: a relation's synthetic permalink ends in the
target's permalink, which itself contains slashes
(``projects/recall-engine/rel/depends_on/projects/vault-engine``), so there
is no reliable way to split one back into its parts by shape. Looking the
whole string up in the index is both simpler and exact.

The scheme prefix is optional everywhere. Agents write ``memory://x`` when
quoting an address and plain ``x`` when they mean "the note called x", and
both must work — a resolver that insisted on the prefix would just teach
models to prepend it mechanically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from palaia_hub.index import Edge, GraphReader, IndexedObservation
from palaia_hub.vault.errors import AmbiguousReferenceError, NoteNotFoundError

#: The URL scheme, with separator.
MEMORY_SCHEME = "memory://"

#: What a resolved reference points at.
RefKind = Literal["note", "block", "observation", "relation"]

#: Glob metacharacters (§3.2). Their presence is what makes a reference a
#: pattern rather than an address.
_GLOB_CHARS = "*?"


@dataclass(frozen=True, slots=True)
class MemoryRef:
    """A parsed ``memory://`` reference, before it is looked up.

    Purely syntactic: :attr:`target` is whatever addressing part the author
    wrote, with the scheme and any ``#anchor`` split off. Whether that names
    a note, an observation or nothing at all is :class:`MemoryResolver`'s
    question.
    """

    raw: str
    target: str
    anchor: str | None = None
    """``^block-id`` (leading caret kept) or a heading, as written after ``#``."""

    @property
    def is_glob(self) -> bool:
        return any(char in self.target for char in _GLOB_CHARS)

    @property
    def block_id(self) -> str | None:
        """The block id when the anchor is a ``^block-id``, else ``None``."""
        if self.anchor is None or not self.anchor.startswith("^"):
            return None
        return self.anchor[1:]

    @property
    def address(self) -> str:
        """The reference re-rendered without the scheme."""
        return self.target if self.anchor is None else f"{self.target}#{self.anchor}"


def parse_memory_ref(raw: str) -> MemoryRef:
    """Split ``raw`` into its addressing part and optional anchor.

    Raises:
        NoteNotFoundError: ``raw`` is empty once the scheme and slashes are
            stripped — there is nothing to resolve, and the caller-facing
            error says so rather than returning a reference to everything.
    """
    text = raw.strip()
    if text.casefold().startswith(MEMORY_SCHEME):
        text = text[len(MEMORY_SCHEME) :]
    text = text.replace("\\", "/").lstrip("/")
    target, _, anchor = text.partition("#")
    target = target.strip().rstrip("/")
    if not target:
        raise NoteNotFoundError(
            f"reference {raw!r} names nothing. Fix: pass a permalink, title, path or "
            f"memory:// URL, e.g. 'memory://projects/api-gateway'."
        )
    return MemoryRef(raw=raw, target=target, anchor=anchor.strip() or None)


@dataclass(frozen=True, slots=True)
class ResolvedRef:
    """One thing a reference resolved to."""

    ref: str
    """The canonical address of the resolved thing (what to quote back)."""

    permalink: str
    """The containing note's permalink — always set, for every kind."""

    kind: RefKind
    anchor: str | None = None
    observation: IndexedObservation | None = None
    relation: Edge | None = None


class MemoryResolver:
    """Resolves ``memory://`` references against one vault's index."""

    def __init__(self, graph: GraphReader, *, vault: str = "") -> None:
        self._graph = graph
        self._vault = vault

    # ------------------------------------------------------------------ public

    def resolve(self, reference: str) -> list[ResolvedRef]:
        """Resolve ``reference`` to one or more addressable things.

        A glob returns every match (possibly none — a pattern matching
        nothing is an empty answer, not an error). Every other form returns
        exactly one element.

        Raises:
            AmbiguousReferenceError: a non-glob reference matched several
                notes at the same resolution tier; the message lists them.
            NoteNotFoundError: nothing matched.
        """
        ref = parse_memory_ref(reference)
        if ref.is_glob:
            return [
                ResolvedRef(ref=permalink, permalink=permalink, kind="note")
                for permalink in self._glob(ref.target)
            ]
        resolved = self._resolve_single(ref)
        if resolved is None:
            raise NoteNotFoundError(
                f"nothing in this vault matches {reference!r}. Fix: check the "
                f"permalink, alias, title or path — resolution order is exact "
                f"permalink, alias, exact title, unique path suffix."
            )
        return [resolved]

    def resolve_one(self, reference: str) -> ResolvedRef:
        """Resolve to exactly one thing; a glob matching ``!= 1`` is an error."""
        matches = self.resolve(reference)
        if not matches:
            raise NoteNotFoundError(
                f"pattern {reference!r} matched no note in this vault. Fix: widen "
                f"the pattern, or name a note directly."
            )
        if len(matches) > 1:
            listed = ", ".join(match.ref for match in matches[:10])
            raise AmbiguousReferenceError(
                f"pattern {reference!r} matched {len(matches)} notes ({listed}"
                f"{', …' if len(matches) > 10 else ''}). Fix: name one of them, or "
                f"use build_context, which accepts several starting points."
            )
        return matches[0]

    # ---------------------------------------------------------------- internals

    def _glob(self, pattern: str) -> list[str]:
        matches = self._graph.matching_glob(pattern)
        if matches:
            return matches
        # `memory://<vault>/<pattern>`: try again without the vault segment,
        # the same fallback order the non-glob path uses below.
        stripped = self._strip_vault(pattern)
        return self._graph.matching_glob(stripped) if stripped is not None else []

    def _resolve_single(self, ref: MemoryRef) -> ResolvedRef | None:
        for candidate in self._candidates(ref.target):
            resolved = self._resolve_candidate(candidate, ref)
            if resolved is not None:
                return resolved
        return None

    def _candidates(self, target: str) -> list[str]:
        """``target``, then ``target`` minus a leading vault-name segment.

        Order matters: a note whose permalink genuinely starts with the vault
        name (``work/onboarding`` in the vault called ``work``) must win over
        the ``memory://work/...`` reading of the same string.
        """
        candidates = [target]
        stripped = self._strip_vault(target)
        if stripped is not None:
            candidates.append(stripped)
        return candidates

    def _strip_vault(self, target: str) -> str | None:
        prefix = f"{self._vault}/"
        if self._vault and target.startswith(prefix) and len(target) > len(prefix):
            return target[len(prefix) :]
        return None

    def _resolve_candidate(self, candidate: str, ref: MemoryRef) -> ResolvedRef | None:
        observation = self._graph.observation_by_ref(candidate)
        if observation is not None:
            return ResolvedRef(
                ref=observation.ref,
                permalink=observation.note_permalink,
                kind="observation",
                observation=observation,
            )
        relation = self._graph.relation_by_ref(candidate)
        if relation is not None:
            return ResolvedRef(
                ref=relation.ref,
                permalink=relation.source,
                kind="relation",
                relation=relation,
            )
        permalink = self._resolve_note(candidate)
        if permalink is None:
            return None
        if ref.anchor is not None:
            return ResolvedRef(
                ref=f"{permalink}#{ref.anchor}",
                permalink=permalink,
                kind="block",
                anchor=ref.anchor,
            )
        return ResolvedRef(ref=permalink, permalink=permalink, kind="note")

    def _resolve_note(self, candidate: str) -> str | None:
        """The four ordered tiers of §3.2. Ambiguity inside a tier raises."""
        for tier, lookup in (
            ("permalink", self._graph.by_permalink),
            ("alias", self._graph.by_alias),
            ("title", self._graph.by_title),
            ("path suffix", self._graph.by_path_suffix),
        ):
            matches = lookup(candidate)
            if len(matches) > 1:
                raise AmbiguousReferenceError(
                    f"{tier} {candidate!r} matches {len(matches)} notes "
                    f"({', '.join(matches)}). Fix: reference one of those "
                    f"permalinks instead."
                )
            if matches:
                return matches[0]
        return None


__all__ = [
    "MEMORY_SCHEME",
    "MemoryRef",
    "MemoryResolver",
    "RefKind",
    "ResolvedRef",
    "parse_memory_ref",
]
