"""Assembles per-profile :class:`PalaiaTokenVerifier` instances from a store.

The one function a gateway-wiring caller (today: tests; once SPEC-113
wires a real gateway into the running hub, that call site too) needs to go
from "a token store" + "a list of profile paths" to the
``dict[str, TokenVerifier]`` :func:`palaia_hub.gateway.build.build_gateway`
accepts as ``token_verifiers``.
"""

from __future__ import annotations

from collections.abc import Iterable

from .store import TokenStore
from .verifier import PalaiaTokenVerifier


def build_profile_verifiers(
    profile_paths: Iterable[str], store: TokenStore
) -> dict[str, PalaiaTokenVerifier]:
    """One :class:`PalaiaTokenVerifier` per profile path, sharing ``store``."""
    return {path: PalaiaTokenVerifier(store, path) for path in profile_paths}


__all__ = ["build_profile_verifiers"]
