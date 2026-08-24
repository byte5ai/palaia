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

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        return _validate_key(value, what="profile path")

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

    @model_validator(mode="after")
    def _check_references(self) -> GatewayConfig:
        vault_keys = [v.key for v in self.vaults]
        if len(set(vault_keys)) != len(vault_keys):
            raise ValueError(f"duplicate vault keys in gateway config: {vault_keys}")
        profile_paths = [p.path for p in self.profiles]
        if len(set(profile_paths)) != len(profile_paths):
            raise ValueError(f"duplicate profile paths in gateway config: {profile_paths}")
        known = set(vault_keys)
        for profile in self.profiles:
            unknown = [v for v in profile.vaults if v not in known]
            if unknown:
                raise ValueError(
                    f"profile {profile.path!r} references unknown vault key(s) {unknown}"
                )
        return self

    def vault(self, key: str) -> VaultMountConfig:
        for vault in self.vaults:
            if vault.key == key:
                return vault
        raise KeyError(f"no vault configured with key {key!r}")
