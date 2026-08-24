"""Gateway configuration: vault mounts and profiles.

Deliberately independent of :mod:`palaia_hub.config` (the hub's own
``HubConfig``/``config.yaml``) — a caller (today: tests and the e2e check;
later: SPEC-113's wiring, once a real vault engine exists) builds a
:class:`GatewayConfig` and a matching ``dict[str, VaultService]`` and passes
both to :func:`palaia_hub.gateway.build.build_gateway`. Nothing here reaches
into ``HubConfig`` or the YAML file, so this SPEC stays decoupled from
however SPEC-108/113 eventually decide to surface gateway settings in the
hub's own config surface.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..upstream.models import UpstreamConfig, check_namespace_conflicts
from .vault_protocol import MEMORY_TOOL_ACTIONS

# MCP profile path segments and vault keys share the tool-name charset
# requirement in practice (they end up embedded in URLs / namespaces), but
# we validate them narrowly here rather than reusing sanitize_tool_name:
# unlike a rename, a bad key/path is a config *error* (fail loudly), not
# something to silently sanitize.
_KEY_CHARSET = "abcdefghijklmnopqrstuvwxyz0123456789-_"


def _validate_key(value: str, *, what: str) -> str:
    if not value:
        raise ValueError(f"{what} must not be empty")
    if any(ch not in _KEY_CHARSET for ch in value):
        raise ValueError(
            f"{what} {value!r} must use only lowercase letters, digits, '-', '_'"
        )
    return value


class VaultMountConfig(BaseModel):
    """One vault as it should be mounted at the gateway.

    ``key`` identifies this vault in :class:`GatewayConfig` / the
    ``vault_services`` mapping passed to ``build_gateway`` — it is a config
    detail, not necessarily exposed. ``name`` is the identity that appears
    in tool names (MASTERPLAN §5.2: ``work_memory_search``); it is
    sanitized like any tool-name component would be, since it becomes part
    of one. ``purpose`` is the user-editable one-line description that
    leads every tool's description text.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    purpose: str = "A palaia memory vault."
    tool_renames: dict[str, str] = Field(default_factory=dict)

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        return _validate_key(value, what="vault key")

    @field_validator("tool_renames")
    @classmethod
    def _check_rename_actions(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(MEMORY_TOOL_ACTIONS))
        if unknown:
            raise ValueError(
                f"tool_renames has unknown action(s) {unknown}; "
                f"valid actions are {list(MEMORY_TOOL_ACTIONS)}"
            )
        return value

    @property
    def namespace(self) -> str:
        """The mount namespace for this vault: ``"<name>_memory"``.

        Composed with an action name via
        :func:`palaia_hub.gateway.naming.compose_tool_name` to predict the
        exact tool name a client will see, e.g. ``work_memory_search``.
        """
        from .naming import sanitize_tool_name

        return f"{sanitize_tool_name(self.name).value}_memory"


#: The gateway profile a vault is mounted under when nothing more specific
#: is configured — the "every vault on one profile" shape this SPEC's
#: zero-config default preserves byte-for-byte (SPEC-301 deliverable #1).
#: Lives here (the schema module) rather than in ``dashboard_api`` (its
#: previous home): every module that resolves or persists gateway config —
#: ``dashboard_api``, ``serve``, ``cli``, ``gateway.settings_bridge`` — needs
#: this same literal, and importing it from the schema is the one direction
#: that adds no cycle.
DEFAULT_GATEWAY_PROFILE = "default"

#: The curator's own profile path (SPEC-206). Defined here, in the schema
#: module, because three unrelated modules need the same literal to *fence*
#: it: :mod:`palaia_hub.curator.profile` (which synthesizes the profile),
#: :mod:`palaia_hub.gateway.api` (which refuses to edit it), and
#: :class:`ProfileConfig` below (which refuses to let an external server be
#: mounted on it at all — SPEC-302 deliverable #6). Importing it from the
#: schema is the one direction that adds no cycle.
CURATOR_PROFILE_PATH = "curator"


class ProfileConfig(BaseModel):
    """One addressable profile: a URL path segment and which vaults it exposes.

    ``path`` is the profile's identity: it is the MCP mount segment
    (``/mcp/<path>``) a client connects to *and* the OAuth resource audience
    it is granted a token for (SPEC-203's ``<issuer>/<path>``) — renaming it
    would silently move every already-connected client and invalidate every
    already-minted token's audience. So ``path`` is set once, at creation,
    and never changed again (SPEC-301 deliverable #2): the runtime profile
    CRUD surface (``palaia_hub.gateway.api``) can create or delete a profile
    by its path, and can edit its ``label``/``vaults``/``stash``, but has no
    "rename path" operation at all — a client that wants a new URL gets a
    new profile, not a mutated one.

    ``label`` is the free-text display name shown in the dashboard's profile
    editor (SPEC-305) — purely cosmetic, defaults to ``path`` when unset, and
    safe to change at any time since nothing outside the dashboard reads it.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = None
    vaults: list[str] = Field(default_factory=list)
    #: Mount the stash tool family (``stash_set``/``stash_get``/...,
    #: SPEC-202) inside this profile too, alongside its vaults' memory
    #: tools — SPEC-301 deliverable #1's "enabled built-ins like stash".
    #: ``False`` (default) leaves a profile exactly as before this field
    #: existed; the hub-wide ``/mcp/stash`` mount (SPEC-202) is unaffected
    #: either way — this only decides whether *this* profile's own MCP
    #: connection also carries those five tools.
    stash: bool = False
    #: Mount the session directory tool family (``directory_register``/
    #: ``directory_heartbeat``/..., SPEC-402) inside this profile too,
    #: same opt-in shape as ``stash`` above. ``False`` (default) leaves a
    #: profile exactly as before this field existed; the hub-wide
    #: ``/mcp/directory`` mount is unaffected either way.
    directory: bool = False
    #: Final (post-namespace) tool names to hide from this profile's own
    #: surface, e.g. ``"work_memory_delete"`` (SPEC-305 deliverable #3): a
    #: profile can mount a whole vault family yet not expose one of its
    #: tools. Applied with FastMCP's own global ``Provider.disable()``
    #: transform on *this profile's* ``FastMCP`` instance (see
    #: ``gateway/build.py``) — not by mutating the shared vault tool
    #: server, which every other profile mounting that vault would also
    #: see. A hidden tool is absent from ``tools/list`` and refused (as
    #: "unknown tool") on call — never merely unlisted.
    hidden_tools: list[str] = Field(default_factory=list)
    #: Expose ``find_tool``/``invoke_tool`` instead of this profile's full
    #: tool surface (SPEC-305 deliverable #4, MASTERPLAN §5.2): a semantic
    #: router backed by the profile's own real tool list, for a tool
    #: collection too large for a client's picker. Off by default and
    #: marked experimental wherever the dashboard shows it — this changes
    #: what a connecting client sees, so it is opt-in per profile, not a
    #: hub-wide setting.
    semantic_routing: bool = False
    #: External MCP servers (SPEC-302) mounted into this profile, by their
    #: :attr:`palaia_hub.upstream.models.UpstreamConfig.key`. An upstream
    #: that is disabled or currently unreachable contributes no tools and
    #: does not stop the profile from building — see
    #: :func:`palaia_hub.gateway.build.build_gateway`.
    upstreams: list[str] = Field(default_factory=list)

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _validate_key(value, what="profile path")

    @model_validator(mode="after")
    def _no_upstreams_on_the_curator(self) -> ProfileConfig:
        """The curator never sees an external server (SPEC-302 deliverable #6).

        Enforced in the schema, not only at mount time, so there is no way
        to *express* the mistake — a config.yaml, a REST payload and a
        runtime rebuild all fail the same way, with the same reason. The
        second half of the fence lives in
        :func:`palaia_hub.gateway.build._build_profile_server`, which
        refuses to mount an upstream onto this path even if a future caller
        ever constructed the profile some other way.
        """
        if self.path == CURATOR_PROFILE_PATH and self.upstreams:
            raise ValueError(
                "the curator profile never mounts an external server: it runs a "
                "model over your own notes, and an outside tool in that session "
                "could exfiltrate them. Fix: mount "
                f"{sorted(self.upstreams)} on a profile your clients use instead."
            )
        return self

    @field_validator("vaults")
    @classmethod
    def _check_vaults_non_empty_entries(cls, value: list[str]) -> list[str]:
        if any(not v for v in value):
            raise ValueError("profile vaults list must not contain empty entries")
        return value

    @property
    def display_label(self) -> str:
        """``label`` if set, else ``path`` — what a UI should show."""
        return self.label or self.path


class GatewayConfig(BaseModel):
    """The full gateway shape: configured vaults, mounted under configured profiles."""

    model_config = ConfigDict(extra="forbid")

    vaults: list[VaultMountConfig] = Field(default_factory=list)
    profiles: list[ProfileConfig] = Field(default_factory=list)
    #: External MCP servers this hub knows about (SPEC-302). Listing one
    #: here does not expose it — a profile has to name it in its own
    #: ``upstreams`` list.
    upstreams: list[UpstreamConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_references(self) -> GatewayConfig:
        vault_keys = [v.key for v in self.vaults]
        if len(set(vault_keys)) != len(vault_keys):
            raise ValueError(f"duplicate vault keys in gateway config: {vault_keys}")
        profile_paths = [p.path for p in self.profiles]
        if len(set(profile_paths)) != len(profile_paths):
            raise ValueError(f"duplicate profile paths in gateway config: {profile_paths}")
        upstream_keys = [u.key for u in self.upstreams]
        if len(set(upstream_keys)) != len(upstream_keys):
            raise ValueError(f"duplicate upstream keys in gateway config: {upstream_keys}")
        known = set(vault_keys)
        known_upstreams = set(upstream_keys)
        for profile in self.profiles:
            unknown = [v for v in profile.vaults if v not in known]
            if unknown:
                raise ValueError(
                    f"profile {profile.path!r} references unknown vault key(s) {unknown}"
                )
            unknown_up = [u for u in profile.upstreams if u not in known_upstreams]
            if unknown_up:
                raise ValueError(
                    f"profile {profile.path!r} references unknown external server(s) "
                    f"{unknown_up}"
                )
        # SPEC-302 deliverable #5: two upstreams (or an upstream and a
        # vault's memory tool family) claiming the same tool-name prefix is
        # refused here, at config time — never resolved by letting whichever
        # mounted last win.
        check_namespace_conflicts(
            self.upstreams,
            reserved={v.namespace: f"vault {v.key!r}" for v in self.vaults},
        )
        return self

    def vault(self, key: str) -> VaultMountConfig:
        for vault in self.vaults:
            if vault.key == key:
                return vault
        raise KeyError(f"no vault configured with key {key!r}")

    def upstream(self, key: str) -> UpstreamConfig:
        for upstream in self.upstreams:
            if upstream.key == key:
                return upstream
        raise KeyError(f"no external server configured with key {key!r}")
