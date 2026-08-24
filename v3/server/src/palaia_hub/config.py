"""Hub configuration: a single ``config.yaml`` in a platform data dir.

Precedence (lowest to highest): built-in defaults < ``config.yaml`` < env
vars (``PALAIA_*``). Zero-config first run creates a commented default file
and starts fine. An invalid file or env value fails startup with a message
naming the file, the offending key, and how to fix it.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

APP_NAME = "palaia-hub"

# The default curator runner command, duplicated here as a plain tuple rather
# than imported from palaia_hub.curator.session: this module must stay
# importable without pulling in the curator package (which imports the
# gateway, which imports fastmcp) — config load happens first, always.
# palaia_hub.curator.session.DEFAULT_RUNNER_COMMAND is the same list, and a
# test asserts the two never drift apart.
_DEFAULT_CURATOR_COMMAND: tuple[str, ...] = (
    "claude",
    "-p",
    "--mcp-config",
    "{mcp_config}",
    "--strict-mcp-config",
    "--allowed-tools",
    "{allowed_tools}",
    "--output-format",
    "text",
)

_ENV_PREFIX = "PALAIA_"

# The config keys that may be overridden by PALAIA_<KEY> env vars. Kept as an
# explicit tuple (rather than deriving from model fields at import time) so
# the mapping from env var name to config key is easy to read and to grep.
_ENV_KEYS = (
    "mode",
    "host",
    "port",
    "log_level",
    "log_format",
    "graceful_shutdown_timeout",
    "auth_enabled",
)

DEFAULT_CONFIG_TEMPLATE = """\
# palaia hub configuration
#
# Generated automatically on first run. Edit freely — invalid values are
# rejected at startup with a message naming this file, the offending key,
# and a fix.
#
# Every setting below may also be overridden by an environment variable
# named PALAIA_<SETTING> (e.g. PALAIA_MODE=cloud), which takes precedence
# over whatever is written here.

# Operating mode: locked | cloud | open
#   locked (default) - MCP + dashboard reachable only over VPN/tailnet
#   cloud             - MCP reachable publicly via a tunnel (Tailscale
#                        Funnel, cloudflared) terminating on a private
#                        `host` below; dashboard stays VPN-only; auth
#                        mandatory. Binding `host` directly to a public
#                        address isn't supported yet — use 'open' for that.
#   open              - both public, `host` may be a public/wildcard bind;
#                        auth mandatory + hardening checklist
mode: locked

# Host/port the hub binds to. In 'cloud' mode this must be a private/VPN
# address (e.g. 127.0.0.1 or a tailnet IP) — see 'mode' above.
host: 127.0.0.1
port: 8420

# Logging: level is one of debug|info|warning|error; format is human|json.
log_level: info
log_format: human

# Seconds to wait for in-flight requests to finish before exiting on
# shutdown (e.g. SIGTERM).
graceful_shutdown_timeout: 30

# Whether MCP clients must present a bearer token (SPEC-108).
#   locked mode - optional; defaults to on anyway (turn off only if every
#                 client on your VPN/tailnet is already trusted).
#   cloud/open  - mandatory; the hub refuses to start MCP endpoints
#                 otherwise. Cannot be turned off in these modes.
auth_enabled: true

# Recall's decay-scoring weights (SPEC-106). Search decides which notes
# *match*; these decide which of the matches come first. Each weight is how
# much its factor may boost a result's relevance rank — with the defaults a
# result can gain at most 65%, so a clearly better textual/semantic match
# still wins. Set a weight to 0 to switch that factor off entirely.
recall:
  # How much a recently modified note is favored.
  recency_weight: 0.25
  # How much a note recall keeps serving is favored.
  access_weight: 0.15
  # How much a load-bearing note (its type, and how much points at it) is
  # favored.
  significance_weight: 0.25
  # Days after which the recency boost has halved.
  half_life_days: 30
  # Access count at which the access boost is maxed out.
  access_saturation: 20
  # Inbound-link count at which the centrality half of significance is maxed.
  centrality_saturation: 12
  # Share of significance that comes from inbound links rather than the
  # note's entry type (0 = type only, 1 = links only).
  centrality_weight: 0.35
  # Recency score for a note carrying no created/modified date at all.
  # Undated is not evidence of stale, so the default sits in the middle.
  unknown_recency: 0.5

# OAuth 2.1 authorization server (SPEC-203). Off by default: it needs an
# `issuer` — the public https URL clients get redirected to — which cannot be
# guessed from the bind address above. Turn it on to connect claude.ai,
# ChatGPT or a phone as a remote connector; per-client `plt_` tokens keep
# working alongside it either way.
oauth:
  enabled: false
  # issuer: https://hub.example.com
  # Access tokens are short-lived JWTs verified locally by each MCP profile.
  access_token_ttl: 900
  refresh_token_ttl: 2592000
  authorization_code_ttl: 120
  # How long a spent refresh token keeps working, so a connector fanned out
  # over web/phone/desktop converges instead of tearing the grant down.
  # Setting this to 0 means strict single-use — expect re-logins.
  refresh_grace_window: 120
  session_ttl: 43200
  # Self-registered clients unused for this long are garbage-collected.
  # Admin-provisioned machine clients are never pruned.
  client_gc_ttl: 2592000
  client_gc_interval: 3600
  # MCP profile paths this server issues audience-scoped tokens for. Must
  # match the gateway's profile paths.
  profiles: []

# The curator (SPEC-206): the background job that turns inbox captures into
# well-placed vault notes. Off by default — it runs a model, which costs
# money. Adding knowledge is autonomous; rewriting, merging or retiring an
# existing note is never autonomous, it becomes a proposal in review/ that
# you approve by flipping its `status` to `approved`.
curator:
  enabled: false
  # The command that runs one curation session. The prompt arrives on the
  # command's stdin; {mcp_config}, {allowed_tools}, {endpoint}, {vault} and
  # {capture_id} are filled in per session. Any CLI that reads a prompt from
  # stdin works here — this is not tied to one provider.
  runner_command:
    - claude
    - -p
    - --mcp-config
    - '{mcp_config}'
    - --strict-mcp-config
    - --allowed-tools
    - '{allowed_tools}'
    - --output-format
    - text
  # Seconds one session may take before it is killed.
  session_timeout: 300
  # Wait this long after a capture arrives, so a burst becomes one pass.
  debounce_seconds: 30
  # Fallback pass interval, for captures written into inbox/ by hand.
  interval_seconds: 900
  # Attempts before a capture is left alone with `status: curation-failed`.
  max_attempts: 3
  # Apply approved proposals in the same pass (no model is ever involved in
  # applying one). Turn off to apply them yourself with
  # `palaia-hub curator apply`.
  auto_apply: true
  # The curator's own token, from `palaia-hub curator token`. Prefer the
  # PALAIA_CURATOR_TOKEN environment variable over writing it here.
  # token:
  # Where a session reaches this hub. Defaults to http://<host>:<port>.
  # endpoint:
"""


class ConfigError(RuntimeError):
    """Raised when the hub configuration cannot be loaded or is invalid.

    The message always names the config file path, the offending key, and a
    concrete fix, per SPEC-101's acceptance criteria.
    """


# RFC 6598 shared address space (100.64.0.0/10) — the CGNAT range Tailscale
# and similar tailnets hand out. Not covered by ipaddress.is_private, so it
# is checked separately below.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _is_private_bind_host(host: str) -> bool:
    """Is ``host`` a bind address that stays off the public internet?

    True for loopback, RFC1918 private ranges, link-local, and the
    Tailscale/tailnet CGNAT range. False for a wildcard bind (``0.0.0.0``/
    ``::`` — reachable on every interface a box has, public ones included),
    an unrecognized literal address, or anything that is not a literal IP
    (a hostname cannot be checked without a DNS lookup, so it is rejected
    rather than trusted).
    """
    if host.lower() == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_unspecified:
        return False
    if addr in _SHARED_ADDRESS_SPACE:
        return True
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


class RecallSettings(BaseModel):
    """Decay-scoring weights for recall ranking (SPEC-106).

    Kept in the hub config rather than hardcoded because ranking quality is
    corpus-shaped: a vault of dated meeting notes wants recency to dominate,
    a vault of standing rules wants significance to. Every field maps
    one-to-one onto :class:`palaia_hub.recall.RankingWeights`; the bounds
    below are what keeps a typo from silently producing nonsense scores
    (a negative weight would *penalize* fresh notes).
    """

    model_config = ConfigDict(extra="forbid")

    recency_weight: float = Field(default=0.25, ge=0.0, le=10.0)
    access_weight: float = Field(default=0.15, ge=0.0, le=10.0)
    significance_weight: float = Field(default=0.25, ge=0.0, le=10.0)
    half_life_days: float = Field(default=30.0, gt=0.0)
    access_saturation: float = Field(default=20.0, gt=0.0)
    centrality_saturation: float = Field(default=12.0, gt=0.0)
    centrality_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    unknown_recency: float = Field(default=0.5, ge=0.0, le=1.0)


class OAuthSettings(BaseModel):
    """The OAuth 2.1 authorization server's settings (SPEC-203).

    Kept here, next to :class:`RecallSettings`, for the same reason: it is
    part of the hub's own ``config.yaml`` surface, and the package that
    consumes it (:mod:`palaia_hub.oauth`) must not be imported by this module
    (it imports *this* one). Every field maps one-to-one onto behaviour in
    that package.

    ``enabled`` is off by default: turning the hub into an authorization
    server requires an ``issuer`` — the public URL clients will be redirected
    to — which cannot be guessed from a bind address.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: Public issuer identifier, e.g. ``https://hub.example.com``. Required
    #: when ``enabled``; every metadata document, ``iss`` claim and canonical
    #: audience is derived from it.
    issuer: str | None = None
    #: Access-token lifetime. Minutes, not hours: access tokens are
    #: self-contained JWTs that the resource side verifies locally, so the
    #: only thing bounding a leaked one is its expiry.
    access_token_ttl: int = Field(default=900, ge=60, le=3600)
    #: Refresh-token lifetime (sliding — each rotation issues a fresh TTL).
    refresh_token_ttl: int = Field(default=30 * 24 * 3600, ge=300)
    #: Authorization-code lifetime. RFC 6749 §4.1.2 recommends ≤ 10 minutes;
    #: a code is exchanged within seconds in practice.
    authorization_code_ttl: int = Field(default=120, ge=10, le=600)
    #: How long a *spent* refresh token keeps working (the multi-device
    #: fan-out lesson, MASTERPLAN §5.5). 0 means strict single-use, which is
    #: exactly the setting that caused daily re-logins in the prototype.
    refresh_grace_window: int = Field(default=120, ge=0, le=3600)
    #: Browser login-session lifetime.
    session_ttl: int = Field(default=12 * 3600, ge=300)
    #: How long an unused self-registered client is kept before the GC prunes
    #: it. Machine and admin clients are never pruned.
    client_gc_ttl: int = Field(default=30 * 24 * 3600, ge=3600)
    #: Minimum interval between GC passes (it is triggered opportunistically
    #: from the token/registration endpoints).
    client_gc_interval: int = Field(default=3600, ge=60)
    #: Which MCP profile paths this authorization server issues tokens for.
    #:
    #: A bridge, not a permanent design: the profiles a hub serves are the
    #: gateway's (:class:`palaia_hub.gateway.config.GatewayConfig`), which
    #: does not reach ``config.yaml`` yet — ``palaia_hub.cli.serve`` still
    #: mounts no gateway (see its comment). Until it does, an operator names
    #: the profiles here so the ``serve`` entry point can host the OAuth
    #: endpoints; a caller that builds a gateway itself passes the real
    #: profile set to :meth:`palaia_hub.oauth.AuthorizationServer.build` and
    #: ignores this list.
    profiles: list[str] = Field(default_factory=list)


class CuratorSettings(BaseModel):
    """The curator's settings (SPEC-206).

    ``enabled`` is off by default: the curator spends money. Turning it on
    mounts the curator MCP profile (``/mcp/curator``, narrowed and guarded —
    see :mod:`palaia_hub.curator.profile`) and starts the scheduled runner.

    ``runner_command`` is the provider-neutral seam the SPEC requires: the
    default is a headless ``claude -p`` reading its prompt from stdin, but
    any CLI that does the same works. Placeholders ``{mcp_config}``,
    ``{allowed_tools}``, ``{endpoint}``, ``{vault}`` and ``{capture_id}`` are
    substituted per session (:class:`palaia_hub.curator.session.
    SubprocessSessionRunner`).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    #: The command that runs one curation session. See the class docstring.
    runner_command: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_CURATOR_COMMAND)
    )
    #: Seconds a single session may take before it is killed.
    session_timeout: float = Field(default=300.0, gt=0.0, le=3600.0)
    #: Seconds to wait after an ``inbox.captured`` event, so a burst of
    #: captures coalesces into one curation pass.
    debounce_seconds: float = Field(default=30.0, ge=0.0, le=3600.0)
    #: Seconds between fallback passes when no event arrives (captures
    #: written into ``inbox/`` by hand produce no event).
    interval_seconds: float = Field(default=900.0, ge=60.0)
    #: Attempts before a capture is retired with ``status: curation-failed``.
    max_attempts: int = Field(default=3, ge=1, le=10)
    #: Apply approved proposals automatically in the same pass. The apply
    #: path has no model in it (SPEC-206 rule 4), so this only decides *when*
    #: an approved proposal is executed, never *whether* a human approved it.
    auto_apply: bool = True
    #: The curator token (profile ``curator``). Prefer the
    #: ``PALAIA_CURATOR_TOKEN`` environment variable — a token in a config
    #: file is a secret in a config file. Mint one with
    #: ``palaia-hub curator token``.
    token: str | None = None
    #: The base URL a curation session reaches this hub at. Defaults to
    #: ``http://<host>:<port>`` from the settings above, which is right for
    #: the normal case (the session runs on the same machine as the hub).
    endpoint: str | None = None


class HubConfig(BaseModel):
    """Validated hub configuration, merged from defaults/file/env."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["locked", "cloud", "open"] = "locked"
    host: str = "127.0.0.1"
    port: int = 8420
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["human", "json"] = "human"
    graceful_shutdown_timeout: float = 30.0
    auth_enabled: bool = True
    recall: RecallSettings = Field(default_factory=RecallSettings)
    oauth: OAuthSettings = Field(default_factory=OAuthSettings)
    curator: CuratorSettings = Field(default_factory=CuratorSettings)

    def curator_endpoint(self) -> str:
        """The base URL a curation session reaches this hub at (SPEC-206)."""
        configured = (self.curator.endpoint or "").strip().rstrip("/")
        if configured:
            return configured
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{host}:{self.port}"

    @model_validator(mode="after")
    def _check_operating_mode_policy(self) -> HubConfig:
        """MASTERPLAN §5.5's per-mode auth policy, enforced in code (SPEC-108).

        ``cloud``/``open`` MUST have auth on — those modes exist to make MCP
        endpoints reachable off the operator's own network, and the hub must
        never serve one that way with no token check. ``cloud`` additionally
        keeps its bind address private: the hub has one listener for both
        the MCP endpoints and the admin dashboard, and the dashboard must
        stay VPN/tailnet-only in ``cloud`` mode (masterplan's mode table) —
        so for Phase 1 (no dual-listener/reverse-proxy split yet), reaching
        the public internet in ``cloud`` mode means a tunnel (Tailscale
        Funnel, cloudflared) terminating on a private address, not a direct
        public/wildcard bind. ``open`` mode has no such restriction — its
        whole point is that the dashboard itself is public too.

        SPEC-203 deliverable #6: **OAuth satisfies the auth mandate too.** The
        rule these modes enforce is "no publicly reachable MCP endpoint
        without an authentication check", and an OAuth 2.1 authorization
        server issuing audience-scoped access tokens is exactly such a check
        — so ``oauth.enabled`` is accepted in place of ``auth_enabled``.
        Turning *both* off in ``cloud``/``open`` is still refused.
        """
        if self.mode in ("cloud", "open") and not (self.auth_enabled or self.oauth.enabled):
            raise ValueError(
                f"mode '{self.mode}' requires an authentication method — MCP "
                f"endpoints would otherwise be reachable over the network with no "
                f"check at all. Fix: set `auth_enabled: true` in config.yaml (or "
                f"PALAIA_AUTH_ENABLED=true) for per-client bearer tokens, or enable "
                f"the OAuth server (`oauth.enabled: true` plus an `oauth.issuer`); "
                f"or set `mode: locked` if every client only ever reaches this hub "
                f"over your own VPN/tailnet."
            )
        if self.mode == "cloud" and not _is_private_bind_host(self.host):
            raise ValueError(
                f"mode 'cloud' requires a private/VPN bind address so the admin "
                f"dashboard never becomes reachable through the same listener "
                f"MCP is exposed on (host is currently {self.host!r}). Fix: set "
                f"`host` to a private address (e.g. 127.0.0.1, or your "
                f"tailnet/Tailscale IP) in config.yaml and reach it publicly via "
                f"a tunnel (Tailscale Funnel, cloudflared); or set `mode: open` "
                f"if you intend the dashboard itself to be public."
            )
        return self


def palaia_home() -> Path:
    """Return the platform data dir for the hub, honoring ``PALAIA_HOME``."""
    override = os.environ.get("PALAIA_HOME")
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir(APP_NAME, appauthor=False))


def config_file_path(home: Path | None = None) -> Path:
    """Return the path to ``config.yaml`` under ``home`` (or the default)."""
    return (home or palaia_home()) / "config.yaml"


def ensure_default_config(path: Path) -> None:
    """Write a commented default config file at ``path`` if none exists."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")


def _read_file_values(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{path}: could not parse YAML ({exc}). Fix: correct the syntax "
            f"in {path}, or delete it to regenerate the default file."
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path}: key '<root>' — expected a mapping of settings, got "
            f"{type(raw).__name__}. Fix: use `key: value` lines in {path}."
        )
    return raw


def _read_env_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in _ENV_KEYS:
        env_name = f"{_ENV_PREFIX}{key.upper()}"
        if env_name in os.environ:
            values[key] = os.environ[env_name]
    return values


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "<root>"
        msg = error["msg"]
        if loc == "<root>" and "Fix:" in msg:
            # A cross-field validator (e.g. _check_operating_mode_policy)
            # already spelled out its own actionable fix — appending the
            # generic "correct '<root>' ... override via PALAIA_<ROOT>"
            # suffix below would only make its message confusing.
            lines.append(f"{path}: {msg.removeprefix('Value error, ')}")
            continue
        env_name = f"{_ENV_PREFIX}{loc.upper()}"
        lines.append(
            f"{path}: key '{loc}' — {msg}. "
            f"Fix: correct '{loc}' in {path}, or override it via {env_name}."
        )
    return "\n".join(lines)


def load_config(home: Path | None = None, *, create_if_missing: bool = True) -> HubConfig:
    """Load and validate the hub config with defaults < file < env precedence.

    Raises:
        ConfigError: the file is unparsable, malformed, or a value (from the
            file or from an env override) fails validation. The message
            names the file, the key, and a fix.
    """
    resolved_home = home or palaia_home()
    path = config_file_path(resolved_home)
    if create_if_missing:
        ensure_default_config(path)

    file_values = _read_file_values(path)
    env_values = _read_env_values()
    merged: dict[str, Any] = {**file_values, **env_values}

    try:
        return HubConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc
