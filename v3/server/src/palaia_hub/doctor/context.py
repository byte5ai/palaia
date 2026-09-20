"""What a doctor pass is allowed to look at, and how the CLI opens it.

:class:`DoctorContext` is deliberately a plain value: the checks never open
a store, a vault or a database themselves. Two callers assemble one —
:func:`open_doctor_context` for ``palaia-hub doctor`` (which opens
everything read-only, on a hub that may well not be running), and, later,
the running hub for its dashboard surface, which already holds all of it.

That split is also what makes the checks testable without a hub: a test
builds a context out of exactly the pieces its check cares about.

Two fields carry honesty rather than data:

* A vault that is missing from :attr:`DoctorContext.indexes` has **no
  index to inspect**, which is itself a finding — not a reason to pretend
  its search is fine.
* :attr:`DoctorContext.live` says whether this context belongs to the
  running hub process. Some signals only exist there (a token's
  ``last_used_at`` is in-memory, so a separate CLI process can never see
  one), and a check must not report their absence as a problem when it is
  really just looking from the outside.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..auth import TokenStore
from ..config import HubConfig, load_config, palaia_home
from ..gateway.config import DEFAULT_GATEWAY_PROFILE
from ..gateway.settings_bridge import GatewaySettingsError, resolve_full_gateway_profiles
from ..index import INDEX_RELATIVE_PATH, VaultIndex
from ..oauth import OAuthStore
from ..oauth.keys import OAUTH_DIR_NAME
from ..oauth.store import DATABASE_FILE
from ..vault import VaultRegistry
from ..vault.engine import VaultEngine


@dataclass(frozen=True, slots=True)
class DoctorContext:
    """Everything the checks may read, already opened by the caller."""

    config: HubConfig
    home: Path
    #: The vaults this pass covers, by registry key.
    vaults: Mapping[str, VaultEngine] = field(default_factory=dict)
    #: The indexes that could be opened, by vault key. A vault absent here
    #: has no index — see the module docstring.
    indexes: Mapping[str, VaultIndex] = field(default_factory=dict)
    tokens: TokenStore | None = None
    #: ``None`` when this hub has no OAuth database at all (never enabled).
    oauth: OAuthStore | None = None
    #: The MCP profile paths this hub serves, or ``None`` when the gateway
    #: shape could not be resolved — checks that compare against it skip
    #: rather than guess.
    profiles: tuple[str, ...] | None = None
    #: True only inside the running hub process (see the module docstring).
    live: bool = False


async def _open_index(engine: VaultEngine) -> VaultIndex | None:
    """Open ``engine``'s index read-only, or ``None`` if it has none yet.

    ``build=False`` and ``start_worker=False`` matter: a diagnosis must not
    rebuild the index or start embedding in the background as a side
    effect of being asked how things are. The existence check matters for
    the same reason — :class:`~palaia_hub.index.VaultIndex` would happily
    *create* an empty database, and an empty index the doctor made itself
    would then be reported as a problem the doctor caused.
    """
    if not (engine.root / INDEX_RELATIVE_PATH).exists():
        return None
    index = VaultIndex(engine)
    await index.open(build=False, start_worker=False)
    return index


def _resolve_profiles(config: HubConfig, vault_keys: Sequence[str]) -> tuple[str, ...] | None:
    """The profile paths this hub serves, or ``None`` if that cannot be said.

    The same resolution ``palaia-hub serve`` uses to build the real gateway
    (SPEC-301's one source of truth), so a token bound to a profile is
    judged against the very list the running hub would mount.

    An empty result is reported as ``None``, not as an empty tuple: a hub
    with no vault yet resolves to no profiles at all, and calling every
    token on it "bound to a profile that no longer exists" would be a
    confident wrong answer to a question whose real answer is "there is no
    vault yet" — which the vaults check already gives.
    """
    try:
        profiles = resolve_full_gateway_profiles(
            config,
            list(vault_keys),
            default_profile=DEFAULT_GATEWAY_PROFILE,
            include_pending=True,
        )
    except GatewaySettingsError:
        return None
    return tuple(profile.path for profile in profiles) or None


@contextlib.asynccontextmanager
async def open_doctor_context(
    *, vault_keys: Sequence[str] = (), home: Path | None = None
) -> AsyncIterator[DoctorContext]:
    """Open everything ``palaia-hub doctor`` needs, and close it afterwards.

    Args:
        vault_keys: only look at these vaults. Empty (the default) means
            every registered vault.
        home: the hub home directory. Defaults to ``PALAIA_HOME`` / the
            platform data directory, like every other command.
    """
    hub_home = home if home is not None else palaia_home()
    # `create_if_missing=False`: a diagnosis must not change the thing it is
    # diagnosing. Every other command writes a default config.yaml (and
    # re-narrows its permissions) on the way past, which would both create a
    # file on a hub that has none and quietly repair the very permissions
    # StorageCheck is there to report. Without a file, the checks run against
    # the defaults — which is exactly what the hub would run on.
    config = load_config(hub_home, create_if_missing=False)
    registry = VaultRegistry(hub_home)
    names = list(vault_keys) or sorted(registry.names())
    engines: dict[str, VaultEngine] = {}
    indexes: dict[str, VaultIndex] = {}
    oauth: OAuthStore | None = None
    try:
        for name in names:
            engine = await registry.get(name)
            engines[name] = engine
            index = await _open_index(engine)
            if index is not None:
                indexes[name] = index
        # Composed by hand rather than through `oauth_dir()`, which creates
        # the directory as a side effect — see the `create_if_missing` note
        # above: looking is not the same as setting up.
        if (hub_home / OAUTH_DIR_NAME / DATABASE_FILE).exists():
            oauth = OAuthStore(hub_home)
            oauth.open()
        yield DoctorContext(
            config=config,
            home=hub_home,
            vaults=engines,
            indexes=indexes,
            tokens=TokenStore(hub_home),
            oauth=oauth,
            profiles=_resolve_profiles(config, sorted(registry.names())),
        )
    finally:
        for index in indexes.values():
            await index.close()
        if oauth is not None:
            oauth.close()
        await registry.aclose()


__all__ = ["DoctorContext", "open_doctor_context"]
