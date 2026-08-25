"""Validating an envelope's ``refs`` against the vaults the sender can read
(SPEC-403 deliverable #1).

The body cap only buys token discipline if the escape hatch actually works:
"write it to memory and reference it" is useless advice if a reference can
point at nothing. So every ``refs`` entry is resolved at *send* time, and a
send with a dangling reference is refused — the sender is still in the
conversation and can fix it, which is the only moment anybody can.

**"a vault the sender can read"** is read off the calling token's scopes
(``vault:<key>:read``, :func:`palaia_hub.auth.scopes.readable_vault_keys`)
and passed down as ``readable_vaults``. A hub with no auth attached to that
mount passes ``None``, meaning "every vault this validator knows" — the
same posture every other tool-level scope check in the gateway takes when
no verifier is mounted (see :func:`palaia_hub.auth.enforcement.
missing_scope_error`'s docstring). A ref that resolves only in a vault the
sender cannot read is treated exactly like one that resolves nowhere: the
error must not become an oracle for "this note exists somewhere you cannot
see".

This module is the one place in :mod:`palaia_hub.messenger` that knows the
recall/index stack exists. The messenger's own service depends on the
narrow :class:`~palaia_hub.messenger.models.RefValidator` protocol instead,
so the mailbox never grows a hard dependency on the search engine.
"""

from __future__ import annotations

from collections.abc import Mapping

from palaia_hub.index import VaultIndex
from palaia_hub.recall.refs import MemoryResolver
from palaia_hub.vault.errors import AmbiguousReferenceError, NoteNotFoundError


class VaultRefValidator:
    """Resolves ``memory://`` refs against one resolver per vault.

    Args:
        resolvers: ``{vault key: resolver over that vault's index}``. An
            empty mapping is a perfectly valid state (a hub with no vaults
            yet) — it simply means every ref is unresolvable, and a send
            carrying one is refused with the reason, rather than a
            reference silently being accepted on a hub that cannot check it.
    """

    def __init__(self, resolvers: Mapping[str, MemoryResolver]) -> None:
        self._resolvers = dict(resolvers)

    @property
    def vault_keys(self) -> frozenset[str]:
        return frozenset(self._resolvers)

    def unresolvable(
        self, refs: list[str], *, readable_vaults: frozenset[str] | None = None
    ) -> list[str]:
        """The subset of ``refs`` resolving in none of the readable vaults."""
        keys = [
            key
            for key in self._resolvers
            if readable_vaults is None or key in readable_vaults
        ]
        return [ref for ref in refs if not self._resolves_anywhere(ref, keys)]

    def _resolves_anywhere(self, ref: str, keys: list[str]) -> bool:
        return any(self._resolves(self._resolvers[key], ref) for key in keys)

    @staticmethod
    def _resolves(resolver: MemoryResolver, ref: str) -> bool:
        try:
            return bool(resolver.resolve(ref))
        except (NoteNotFoundError, AmbiguousReferenceError):
            # Ambiguity counts as "does not resolve": an envelope's ref has
            # to name one thing, and "it matched three notes" is exactly as
            # unusable to the recipient as "it matched none".
            return False


def build_vault_ref_validator(indexes: Mapping[str, VaultIndex]) -> VaultRefValidator:
    """A validator over every open vault index on this hub.

    Called from :func:`palaia_hub.serve.build_production_app`, which already
    holds ``{vault name: VaultIndex}``. Each resolver is constructed with
    its vault's name so a fully-qualified ``memory://<vault>/<permalink>``
    reference resolves the same way it does through
    :class:`palaia_hub.recall.service.RecallService`.
    """
    return VaultRefValidator(
        {name: MemoryResolver(index.graph, vault=name) for name, index in indexes.items()}
    )


__all__ = ["VaultRefValidator", "build_vault_ref_validator"]
