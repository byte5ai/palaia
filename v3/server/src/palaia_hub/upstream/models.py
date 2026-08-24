"""The upstream-server registry's schema (SPEC-302 deliverable #1).

One external MCP server the operator connected: a remote HTTP endpoint, or a
local command palaia spawns. Deliberately **import-free** with respect to the
rest of ``palaia_hub``:

- :mod:`palaia_hub.config` imports :class:`UpstreamConfig` directly (as
  ``GatewayUpstreamSettings``) rather than keeping a hand-maintained twin of
  it, and that module must stay importable without pulling in fastmcp — so
  nothing here may import :mod:`palaia_hub.gateway` (whose package
  ``__init__`` does) or :mod:`palaia_hub.upstream.service` (which does too).
  The namespace/key charset rules are therefore re-stated here as local
  regexes rather than borrowed from ``gateway.config``/``gateway.naming``.
- The parent package's ``__init__`` is deliberately empty of imports for the
  same reason: ``import palaia_hub.upstream.models`` must not drag a
  transport layer in behind it.

Credentials never appear in this model. An ``http`` upstream names the
*secret* that holds its bearer token or API key
(:class:`UpstreamAuthConfig.secret_name`); a ``stdio`` upstream names which
secrets to inject into which environment variables
(:attr:`UpstreamConfig.env_secrets`). Both are looked up at connect time
through :class:`palaia_hub.upstream.secrets.SecretStore`, so this model — and
therefore ``config.yaml``, which is plain text — carries names only.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: An upstream's config identity: the key REST addresses it by, a profile
#: lists in its ``upstreams``, and ``config.yaml`` stores it under.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

#: An upstream's tool-name prefix. Narrower than the key charset (``-`` is
#: not a legal MCP tool-name character), and a *loud* error rather than a
#: silent sanitization: a mis-typed namespace changes every tool name a
#: connected client sees, which is not something to fix behind the
#: operator's back.
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: How long a connect/initialize/tools-list probe may take before the
#: upstream is called down. Bounded by construction (SPEC-302 deliverable
#: #4: "bounded connect timeouts; the mount must not block hub startup").
DEFAULT_CONNECT_TIMEOUT = 8.0

UpstreamKind = Literal["http", "stdio"]


class UpstreamAuthConfig(BaseModel):
    """Static header auth for an ``http`` upstream (SPEC-302 deliverable #3).

    ``secret_name`` names an entry in the encrypted secret store; its value
    is substituted into ``value_template`` at connect time. The default
    template produces the ordinary ``Authorization: Bearer <token>``; an
    upstream wanting ``X-API-Key: <key>`` sets ``header: X-API-Key`` and
    ``value_template: "{secret}"``.

    Full OAuth *client* flows against a third-party authorization server are
    an explicit non-goal of this SPEC: the v1 path is pasting a token into
    the secret store by hand, which the dashboard says plainly rather than
    implying an automatic login.
    """

    model_config = ConfigDict(extra="forbid")

    header: str = "Authorization"
    value_template: str = "Bearer {secret}"
    secret_name: str

    @field_validator("header")
    @classmethod
    def _check_header(cls, value: str) -> str:
        if not value or any(ch.isspace() or ch == ":" for ch in value):
            raise ValueError(
                f"auth header name {value!r} must be a single HTTP header name, "
                "with no spaces or ':'"
            )
        return value

    @field_validator("value_template")
    @classmethod
    def _check_template(cls, value: str) -> str:
        if "{secret}" not in value:
            raise ValueError(
                "auth value_template must contain '{secret}' — that is where the "
                "stored secret is substituted (e.g. 'Bearer {secret}')"
            )
        return value


class UpstreamConfig(BaseModel):
    """One external MCP server, as configured.

    Args:
        key: config identity (``[a-z0-9_-]``), set once.
        kind: ``http`` for a remote streamable-HTTP endpoint, ``stdio`` for a
            local command palaia spawns and talks to over its pipes.
        display_name: what a person calls this server ("Linear", "My
            weather box"). Shown in the dashboard and in the provenance line
            a profile's IDENTITY block carries.
        namespace: the tool-name prefix its tools appear under
            (``<namespace>_<tool>``). Defaults to ``key`` with ``-`` turned
            into ``_``.
        enabled: ``False`` keeps the entry but mounts nothing — the way to
            switch a server off without losing how it was configured.
        url: the endpoint, for ``kind: http``.
        command / args / cwd: the process to spawn, for ``kind: stdio``.
        env: plain (non-secret) environment for a ``stdio`` child.
        env_secrets: ``{ENV_VAR: secret name}`` — each named secret is
            decrypted and injected into the child's environment at spawn
            time, so a token never appears in ``config.yaml`` or in a
            process listing's arguments.
        headers: plain (non-secret) extra headers for an ``http`` upstream.
        auth: static header auth from the secret store, for ``http``.
        tool_renames: ``{upstream tool name: pre-namespace replacement}`` —
            the same pre-namespace contract every rename in this repository
            uses (SPEC-002 FINDINGS Q4; see
            :mod:`palaia_hub.gateway.naming`).
        connect_timeout: seconds a probe or connect may take.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    kind: UpstreamKind
    display_name: str
    namespace: str | None = None
    enabled: bool = True

    url: str | None = None

    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    env_secrets: dict[str, str] = Field(default_factory=dict)

    headers: dict[str, str] = Field(default_factory=dict)
    auth: UpstreamAuthConfig | None = None

    tool_renames: dict[str, str] = Field(default_factory=dict)
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError(
                f"upstream key {value!r} must be 1-64 characters of lowercase "
                "letters, digits, '-' or '_', starting with a letter or digit"
            )
        return value

    @field_validator("namespace")
    @classmethod
    def _check_namespace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _NAMESPACE_RE.match(value):
            raise ValueError(
                f"upstream namespace {value!r} must be 1-64 characters of "
                "lowercase letters, digits or '_', starting with a letter — it "
                "becomes the prefix of every tool name this server contributes"
            )
        return value

    @field_validator("display_name")
    @classmethod
    def _check_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be empty — it is what a person reads")
        return value

    @field_validator("connect_timeout")
    @classmethod
    def _check_timeout(cls, value: float) -> float:
        if not 0.1 <= value <= 120:
            raise ValueError("connect_timeout must be between 0.1 and 120 seconds")
        return value

    @model_validator(mode="after")
    def _check_kind_fields(self) -> UpstreamConfig:
        if self.kind == "http":
            if not self.url:
                raise ValueError(f"upstream {self.key!r} is kind 'http' and needs a `url`")
            if self.command:
                raise ValueError(
                    f"upstream {self.key!r} is kind 'http' but also sets `command`; "
                    "pick one (use kind 'stdio' for a local command)"
                )
            if self.env_secrets or self.env:
                raise ValueError(
                    f"upstream {self.key!r} is kind 'http'; `env`/`env_secrets` only "
                    "apply to a 'stdio' upstream (use `auth`/`headers` instead)"
                )
        else:
            if not self.command:
                raise ValueError(f"upstream {self.key!r} is kind 'stdio' and needs a `command`")
            if self.url:
                raise ValueError(
                    f"upstream {self.key!r} is kind 'stdio' but also sets `url`; "
                    "pick one (use kind 'http' for a remote endpoint)"
                )
            if self.auth or self.headers:
                raise ValueError(
                    f"upstream {self.key!r} is kind 'stdio'; `auth`/`headers` only "
                    "apply to an 'http' upstream (use `env_secrets` instead)"
                )
        for env_var in self.env_secrets:
            if not env_var or not env_var.replace("_", "").isalnum():
                raise ValueError(
                    f"upstream {self.key!r}: {env_var!r} is not a usable environment "
                    "variable name (letters, digits and '_' only)"
                )
        return self

    @property
    def mount_namespace(self) -> str:
        """The tool-name prefix actually used: ``namespace``, else ``key``."""
        return self.namespace or self.key.replace("-", "_")

    @property
    def target(self) -> str:
        """A one-line, credential-free description of where this points."""
        if self.kind == "http":
            return self.url or ""
        return " ".join([self.command or "", *self.args]).strip()


class UpstreamConflictError(ValueError):
    """Two upstreams (or an upstream and a vault) claim the same namespace,
    or two upstream tools would land on the same final name.

    Raised at config time — never resolved by letting the last write win
    (SPEC-302 deliverable #5: "conflicts refused loudly at config time, not
    silently last-write-wins").
    """


def check_namespace_conflicts(
    upstreams: list[UpstreamConfig], *, reserved: dict[str, str] | None = None
) -> None:
    """Refuse a set of upstreams whose namespaces collide.

    Args:
        upstreams: every configured upstream (enabled or not — a disabled
            entry still owns its namespace, so enabling it later can never
            surprise anyone with a conflict).
        reserved: ``{namespace: what already owns it}`` — the vault
            namespaces (``<vault>_memory``) and any built-in prefix, so an
            upstream cannot shadow a memory tool family.

    Raises:
        UpstreamConflictError: naming both claimants and the namespace.
    """
    owners: dict[str, str] = dict(reserved or {})
    for upstream in upstreams:
        namespace = upstream.mount_namespace
        existing = owners.get(namespace)
        if existing is not None:
            raise UpstreamConflictError(
                f"namespace {namespace!r} is claimed by both {existing} and "
                f"upstream {upstream.key!r} ({upstream.display_name!r}). Every "
                "tool from both would collide. Fix: give one of them a different "
                "`namespace`."
            )
        owners[namespace] = f"upstream {upstream.key!r}"


__all__ = [
    "DEFAULT_CONNECT_TIMEOUT",
    "UpstreamAuthConfig",
    "UpstreamConfig",
    "UpstreamConflictError",
    "UpstreamKind",
    "check_namespace_conflicts",
]
