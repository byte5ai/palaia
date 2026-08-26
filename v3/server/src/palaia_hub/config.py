"""Hub configuration: a single ``config.yaml`` in a platform data dir.

Precedence (lowest to highest): built-in defaults < ``config.yaml`` < env
vars (``PALAIA_*``). Zero-config first run creates a commented default file
and starts fine. An invalid file or env value fails startup with a message
naming the file, the offending key, and how to fix it.
"""

from __future__ import annotations

import ipaddress
import os
import warnings
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# SPEC-502: the hub's one on-disk posture rule, applied to `config.yaml`
# below. Stdlib only, so it is safe to import this early.
from .security.files import harden_directory, harden_file

# SPEC-302: the external-server schema, imported rather than duplicated.
# `palaia_hub.upstream.models` (and its package `__init__`) import nothing
# from the rest of `palaia_hub` and nothing from fastmcp, precisely so this
# module can use it while still loading before any transport layer exists.
from .upstream.models import UpstreamConfig as GatewayUpstreamSettings

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
#
# Which MCP resources this server issues audience-scoped tokens for is no
# longer set here (SPEC-301): it always follows the gateway's own profiles
# below (or the single `default` profile over every vault, when no `gateway:`
# section is present) — one source of truth for "what this hub serves".
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
  # Sign in with an identity provider instead of the local password
  # (SPEC-204). Uncomment ONE of the blocks below. Setting this removes the
  # password sign-in route entirely — "one door only" (MASTERPLAN §5.5):
  # two doors into the same room mean the weaker one decides how strong the
  # room is. The provider's token is used once, to read the signed-in
  # username, and is never stored.
  # idp:
  #   provider: github
  #   github:
  #     client_id: "..."
  #     client_secret: "..."
  #     allowed_users: ["your-github-username"]
  # idp:
  #   provider: oidc
  #   oidc:
  #     discovery_url: "https://accounts.example.com/.well-known/openid-configuration"
  #     client_id: "..."
  #     client_secret: "..."
  #     allowed_users: ["you@example.com"]
  #     display_name: "Example Workspace"

# The dashboard's own sign-in gate (SPEC-401). Left unset, it follows the
# operating mode above: required when the dashboard is public ('open'), on
# by default when MCP is public but the dashboard is not ('cloud'), and off
# on a private network ('locked'), where the first-run wizard has to be
# reachable before any account exists. Set it yourself to require signing in
# on a private network too — it takes effect once you have set a password
# (`palaia-hub oauth set-password`) or configured a sign-in provider.
# dashboard:
#   require_sign_in: true

# Public exposure (SPEC-205): how this hub is reached from outside the
# operator's own network in 'cloud'/'open' mode. Purely descriptive — it
# does not change what the hub binds to (see 'host'/'mode' above) — but the
# exposure wizard (dashboard) uses it to fill in the connect-a-client page
# and to run its honest public-URL reachability self-test.
exposure:
  # The https URL this hub is reachable at from outside (a tunnel hostname,
  # or your own reverse proxy's public name). Unset until the wizard's
  # self-test passes, or you set it here yourself.
  # public_url: https://hub.example.com
  # How the public URL above is served: 'tailscale', 'cloudflared', or
  # 'reverse_proxy' (bring-your-own). Purely informational.
  tunnel: null

# The gateway's shape (SPEC-301): which MCP profiles this hub serves, which
# vaults each one mounts, and any per-vault tool renames or per-profile
# built-ins (like the stash tools). Absent (the default, as below) — every
# registered vault is served on one profile named 'default', exactly as
# before this section existed; nothing to change for a zero-config hub.
#
# Uncomment and edit to shape it yourself, or use the dashboard's profile
# editor / `POST /api/gateway/profiles` — either way edits here are picked
# up live, no restart needed, and a REST-made edit is written back here.
#
# gateway:
#   # Per-vault identity overrides (optional — a vault not listed here uses
#   # its own name/purpose and no tool renames, same as always).
#   vaults:
#     - key: work
#       name: work
#       purpose: "Work notes and decisions."
#       tool_renames:
#         search: find
#   # Which profiles exist, and what each one mounts. A profile's `path` is
#   # its identity (the MCP URL segment, and the OAuth resource audience if
#   # OAuth is on) — set once, never renamed; give it a `label` instead if
#   # you want a friendlier display name.
#   profiles:
#     - path: default
#       label: Default
#       vaults: [work]
#       stash: false
#       directory: false
#       messenger: false
#       # Other MCP servers this profile also offers, by key (see below).
#       upstreams: [linear]
#   # Other people's MCP servers, connected once here instead of in every
#   # client's own config file. `kind: http` is a server on the internet;
#   # `kind: stdio` is a program palaia starts on this machine and talks to.
#   # Their tools appear as `<namespace>_<tool>` on whichever profiles list
#   # them above, and you can rename any of them.
#   #
#   # API keys and tokens NEVER go in this file. Store the value once (the
#   # dashboard, or `PUT /api/secrets/<name>`) and refer to it by name here;
#   # it is encrypted in secrets.sqlite3 and never shown again.
#   #
#   # palaia does not log in to other services for you: if a service issues
#   # you a token, paste it in yourself. (palaia's own `oauth:` server above
#   # is a different thing — that is how your clients log in to palaia.)
#   upstreams:
#     - key: linear
#       kind: http
#       display_name: Linear
#       url: https://mcp.linear.app/mcp
#       namespace: linear
#       enabled: true
#       auth:
#         header: Authorization
#         value_template: "Bearer {secret}"
#         secret_name: linear-token
#     - key: weather
#       kind: stdio
#       display_name: Weather box
#       command: /usr/local/bin/weather-mcp
#       args: ["--stdio"]
#       env_secrets:
#         WEATHER_API_KEY: weather-key

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

# The marketplace's curated add-on index (MASTERPLAN §5.3): where to fetch
# palaia's signed, curated list of add-ons from. The signature's public key
# is pinned in code, never here — changing this URL alone cannot make the
# hub trust a different signer. null uses the built-in default URL.
market:
  index_url: null
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


class GitHubIdpSettings(BaseModel):
    """"Sign in with GitHub" (SPEC-204). Zero scopes are ever requested —
    the token is used once to read the signed-in username, then discarded.
    """

    model_config = ConfigDict(extra="forbid")

    client_id: str
    client_secret: str
    #: Usernames allowed to sign in, compared case-folded (GitHub usernames
    #: are themselves case-insensitive, so this matches the provider's own
    #: notion of identity rather than a stricter one of ours).
    allowed_users: list[str] = Field(min_length=1)


class OidcIdpSettings(BaseModel):
    """A generic OpenID Connect provider (SPEC-204), discovery-configured.

    Only the discovery URL, a client id/secret and an allow-list are asked
    for — every endpoint the flow needs comes from the provider's own
    ``/.well-known/openid-configuration`` document, fetched once and reused
    for the life of the process.
    """

    model_config = ConfigDict(extra="forbid")

    discovery_url: str
    client_id: str
    client_secret: str
    allowed_users: list[str] = Field(min_length=1)
    #: The claim in the provider's user-info response that carries the
    #: username to check against ``allowed_users``. ``preferred_username``
    #: is the OIDC-standard field for this; some providers only populate
    #: ``email``, so it is configurable.
    username_claim: str = "preferred_username"
    #: The provider's plain-language name, e.g. ``"Acme Workspace"``. Shown
    #: on the sign-in button as "Sign in with {display_name}" — the jargon
    #: rule (no protocol acronyms user-facing) means this hub cannot invent
    #: a generic label on the operator's behalf.
    display_name: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_discovery_url(self) -> OidcIdpSettings:
        if not self.discovery_url.lower().startswith("https://"):
            raise ValueError(
                "oauth.idp.oidc.discovery_url must be an https URL. Fix: use the "
                "provider's `.well-known/openid-configuration` https URL."
            )
        return self


class IdpSettings(BaseModel):
    """Which identity provider (if any) fronts sign-in, and its settings.

    **One door only** (MASTERPLAN §5.5): when this is set, the local owner
    password route is not registered at all — see
    :mod:`palaia_hub.oauth.routes`. Exactly one of ``github``/``oidc`` must
    be present, matching ``provider``.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["github", "oidc"]
    github: GitHubIdpSettings | None = None
    oidc: OidcIdpSettings | None = None

    @model_validator(mode="after")
    def _check_matching_block(self) -> IdpSettings:
        block = self.github if self.provider == "github" else self.oidc
        if block is None:
            raise ValueError(
                f"oauth.idp.provider is {self.provider!r} but oauth.idp.{self.provider} "
                f"is not set. Fix: add an `oauth.idp.{self.provider}:` block with its "
                f"settings, or change `provider`."
            )
        other = "oidc" if self.provider == "github" else "github"
        if getattr(self, other) is not None:
            raise ValueError(
                f"oauth.idp.provider is {self.provider!r} but oauth.idp.{other} is also "
                f"set. Fix: remove the `oauth.idp.{other}:` block — only one identity "
                f"provider may be configured at a time."
            )
        return self


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
    #: **Deprecated (SPEC-301), ignored.** Used to be how an operator named
    #: which MCP profiles this authorization server issues tokens for — a
    #: bridge from before the gateway's own shape reached ``config.yaml``.
    #: Now the AS always reads that from the gateway's own profiles (the
    #: ``gateway:`` section below, or the single ``default`` profile when
    #: that section is absent) — one source of truth for "what this hub
    #: serves", per SPEC-301 deliverable #3. Kept only so an old
    #: ``config.yaml`` that still sets this parses without error; see
    #: :func:`load_config`'s deprecation warning. Fix: delete this key.
    profiles: list[str] = Field(default_factory=list)
    #: An identity provider fronting sign-in (SPEC-204). ``None`` (default)
    #: keeps the local owner password as the only door; setting this removes
    #: the password route entirely rather than adding a second door next to
    #: it (MASTERPLAN §5.5's "one door only" rule).
    idp: IdpSettings | None = None

    @model_validator(mode="after")
    def _warn_deprecated_profiles(self) -> OAuthSettings:
        if self.profiles:
            warnings.warn(
                "config.yaml: `oauth.profiles` is deprecated and no longer read — "
                "the OAuth server now always issues tokens for the gateway's own "
                "profiles (the `gateway:` section, or the single 'default' profile "
                "when that section is absent). Fix: remove `oauth.profiles` from "
                "config.yaml.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self


class ExposureSettings(BaseModel):
    """Public-exposure metadata (SPEC-205): descriptive, not enforcing.

    Distinct from ``mode``/``host``/``auth_enabled`` above: those decide
    what the hub *does* (bind address, whether it refuses to start without
    auth); this section records what the operator has told the hub about
    how a tunnel or reverse proxy makes it reachable, so the exposure
    wizard can fill in the connect-a-client page and self-test the public
    URL without asking twice. Leaving it unset changes nothing else.
    """

    model_config = ConfigDict(extra="forbid")

    #: The https URL this hub is reachable at from outside the operator's
    #: own network. Not validated against ``host``/``mode`` here — the
    #: wizard's self-test (``palaia_hub.modes.selftest``) is what actually
    #: confirms it resolves and answers, honestly, rather than this model
    #: pretending to.
    public_url: str | None = None
    #: How ``public_url`` is served. Purely informational — it only
    #: changes which copy-paste config the wizard offers, never the hub's
    #: own behavior.
    tunnel: Literal["tailscale", "cloudflared", "reverse_proxy"] | None = None


class DashboardSettings(BaseModel):
    """The dashboard's own admin session gate (SPEC-401).

    One knob, and it is deliberately three-valued: ``None`` (the default,
    and what a config.yaml with no ``dashboard:`` section parses to) means
    "whatever this operating mode requires" — mandatory in ``open``, on in
    ``cloud``, off in ``locked``. See
    :func:`palaia_hub.admin_session.sign_in_required` for why each mode
    defaults that way; an explicit ``true``/``false`` overrides it in
    ``locked`` and ``cloud``, and ``open`` refuses ``false`` outright (a
    public dashboard with no sign-in is the one combination the masterplan's
    mode table rules out).
    """

    model_config = ConfigDict(extra="forbid")

    #: ``None`` = follow the operating mode's own policy.
    require_sign_in: bool | None = None


class GatewayVaultSettings(BaseModel):
    """One vault's gateway identity override (SPEC-301 deliverable #1).

    A vault registered with :class:`~palaia_hub.vault.VaultRegistry` but
    absent from ``gateway.vaults`` uses its own name/purpose and no tool
    renames — exactly as before this section existed. Listing it here
    overrides the display name, one-line purpose, and/or per-tool renames
    (SPEC-105's ``tool_renames``: base action name → desired tool name,
    applied wherever this vault is mounted) that the gateway actually
    builds tools from.

    Deliberately duplicated here rather than importing
    :class:`palaia_hub.gateway.config.VaultMountConfig` directly: this
    module must stay importable without pulling in the gateway package
    (which imports fastmcp) — see :data:`_DEFAULT_CURATOR_COMMAND`'s
    comment above for the same rule applied to the curator. A test
    (``tests/gateway/test_settings_bridge.py``) asserts the two shapes
    never drift apart.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    #: Display name shown in tool names (e.g. ``work`` → ``work_memory_*``).
    #: ``None`` keeps the vault's own name (the registry key, normally).
    name: str | None = None
    #: One-line purpose leading every one of this vault's tool descriptions.
    #: ``None`` keeps whatever the vault's own manifest declares.
    purpose: str | None = None
    #: Base action name → desired tool name (pre-namespace). Invalid
    #: characters are sanitized with a warning at build time, same as any
    #: other rename (SPEC-105).
    tool_renames: dict[str, str] = Field(default_factory=dict)


class GatewayProfileSettings(BaseModel):
    """One MCP profile's shape (SPEC-301 deliverable #1).

    ``path`` is this profile's permanent identity — the MCP mount segment
    and (when OAuth is on) its resource audience. It is set once, here or
    via ``POST /api/gateway/profiles``, and never renamed afterwards; use
    ``label`` for a friendly display name instead. See
    :class:`palaia_hub.gateway.config.ProfileConfig`'s docstring for why.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str | None = None
    vaults: list[str] = Field(default_factory=list)
    #: Mount the stash tool family inside this profile too (SPEC-202/301).
    stash: bool = False
    #: Mount the session directory tool family inside this profile too
    #: (SPEC-402), same opt-in shape as ``stash`` above.
    directory: bool = False
    #: Mount the messenger tool family inside this profile too (SPEC-403),
    #: same opt-in shape again. Refused on the curator profile — see
    #: ``palaia_hub.gateway.config.ProfileConfig``.
    messenger: bool = False
    #: Final (post-namespace) tool names hidden from this profile (SPEC-305
    #: deliverable #3). See ``palaia_hub.gateway.config.ProfileConfig``.
    hidden_tools: list[str] = Field(default_factory=list)
    #: Expose ``find_tool``/``invoke_tool`` instead of the full surface
    #: (SPEC-305 deliverable #4). See ``ProfileConfig``.
    semantic_routing: bool = False
    #: External MCP servers (SPEC-302) mounted into this profile, by key —
    #: each has to appear in ``gateway.upstreams`` below. Listing a server
    #: there connects it; listing it *here* is what exposes its tools to the
    #: clients using this profile.
    upstreams: list[str] = Field(default_factory=list)


class GatewaySettings(BaseModel):
    """The ``gateway:`` config.yaml section (SPEC-301): profiles as
    first-class, operator-editable configuration.

    Absent (``None`` on :class:`HubConfig`, the default) — the gateway is
    built exactly as it always has been: one profile named ``default``
    mounting every registered vault, no renames, no stash. Present with an
    empty ``profiles`` list — same default, so adding ``gateway:\\n  vaults:
    ...`` alone (identity overrides, no profile shape yet) changes nothing
    about which profiles exist. Present with ``profiles`` populated — that
    list is authoritative for which profiles exist and what each mounts;
    see :mod:`palaia_hub.gateway.settings_bridge` for how it is resolved
    against the vaults actually registered, and how a runtime
    create/edit/delete through ``POST /api/gateway/profiles`` is written
    back here.

    The curator's own profile (``/mcp/curator``, SPEC-206) is never listed
    here — it is synthesized separately from ``curator.enabled``, the same
    way it always was; this section is only ever the *ordinary* profiles.
    """

    model_config = ConfigDict(extra="forbid")

    vaults: list[GatewayVaultSettings] = Field(default_factory=list)
    profiles: list[GatewayProfileSettings] = Field(default_factory=list)
    #: External MCP servers this hub connects (SPEC-302). Unlike the two
    #: lists above, this one is **not** duplicated from the gateway package
    #: — :class:`palaia_hub.upstream.models.UpstreamConfig` is imported
    #: directly, because that module was written to be import-free with
    #: respect to the rest of ``palaia_hub`` for exactly this reason (see
    #: its docstring). One shape, no twin to keep in sync; the "duplicate it
    #: to stay fastmcp-free" rule the two settings classes above follow is
    #: satisfied here by the *model* being fastmcp-free instead.
    #:
    #: Credentials are never stored here: an entry names the secret it needs
    #: (:class:`~palaia_hub.upstream.models.UpstreamAuthConfig.secret_name`,
    #: ``env_secrets``) and the value lives encrypted in
    #: ``<home>/secrets.sqlite3``.
    upstreams: list[GatewayUpstreamSettings] = Field(default_factory=list)


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


class MarketSettings(BaseModel):
    """The marketplace's curated-index source (SPEC-303 deliverable #2).

    Only the index *URL* is configurable — the Ed25519 public key it must
    verify against is pinned in code
    (``palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64``), never here.
    A configurable trust anchor would let a config-file edit alone make
    the hub trust an attacker's index; the URL merely says where to look
    for a document that still has to carry a valid signature from the
    one key this hub ships pinned to.
    """

    model_config = ConfigDict(extra="forbid")

    #: ``None`` means "use palaia_hub.market.curated.DEFAULT_INDEX_URL".
    #: Kept optional (rather than defaulting here) so the default lives in
    #: exactly one place.
    index_url: str | None = None


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
    exposure: ExposureSettings = Field(default_factory=ExposureSettings)
    market: MarketSettings = Field(default_factory=MarketSettings)
    #: The dashboard's admin session gate (SPEC-401).
    dashboard: DashboardSettings = Field(default_factory=DashboardSettings)
    #: The gateway's profiles/vault-identity shape (SPEC-301). ``None`` (the
    #: default, and what an old config.yaml with no ``gateway:`` section
    #: parses to) means "today's zero-config behavior": every vault on one
    #: ``default`` profile. See :class:`GatewaySettings`.
    gateway: GatewaySettings | None = None

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
        if self.mode == "open" and self.dashboard.require_sign_in is False:
            # SPEC-401 deliverable #4: sign-in is mandatory in `open` mode —
            # that mode puts the dashboard itself on the public internet, so
            # "public admin surface, no sign-in" is the one combination the
            # masterplan's mode table rules out. Refused loudly rather than
            # silently ignored, so an operator who wrote this never believes
            # it took effect.
            raise ValueError(
                "mode 'open' cannot set `dashboard.require_sign_in: false` — in "
                "this mode the dashboard itself is reachable from the internet, "
                "so signing in is mandatory. Fix: remove that key (or set it to "
                "true), or use `mode: cloud` if you want the dashboard to stay "
                "on your own network."
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


def harden_config_file(path: Path) -> None:
    """Narrow ``config.yaml`` and the hub home that holds it (SPEC-502).

    ``config.yaml`` is documentation-shaped and mostly boring — but it is
    also where an identity provider's ``client_secret`` is configured
    (:class:`IdpSettings`), and where the issuer, bind address and exposure
    URL of the hub are written down. Before this SPEC it was created with
    the process umask (usually ``0644``) inside a ``0755`` home, so on a
    shared machine any other account could read the provider secret. It now
    gets the same owner-only posture as every other file the hub writes.
    """
    harden_directory(path.parent)
    harden_file(path)


def ensure_default_config(path: Path) -> None:
    """Write a commented default config file at ``path`` if none exists."""
    if path.exists():
        harden_config_file(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    harden_config_file(path)


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
        config = HubConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc
    # Issue #242 / SPEC-401 deliverable #5: `open` mode's contract (the
    # masterplan mode table) is a PUBLIC dashboard with mandatory sign-in.
    # The sign-in now exists (palaia_hub.admin_session), so the blanket
    # refusal is lifted — but only for a hub that actually has a way in.
    # Without one, choosing `open` would put every admin endpoint — token
    # minting, profile editing, mode changes, vault contents — on the public
    # internet with no check at all, so that config is still refused, in the
    # same place and with a message that now names the missing piece.
    # Checked here rather than in HubConfig's own validator because the
    # answer depends on state outside the config file (whether an owner
    # account exists under `home`), which a pure model validator has no
    # business reading.
    if config.mode == "open":
        # Imported here, not at module scope: `admin_session` reads the
        # session/CSRF cookie names from `palaia_hub.oauth`, whose package
        # chain imports this module back. A function-level import keeps that
        # edge out of the import graph entirely.
        from .admin_session import sign_in_configured

        if not sign_in_configured(config, resolved_home):
            raise ConfigError(
                f"{path}: mode 'open' makes this dashboard reachable from the "
                f"internet, so it needs a way for you to sign in first — and "
                f"this hub has none configured yet. Fix: turn the sign-in "
                f"server on (`oauth.enabled: true` plus an `oauth.issuer`) and "
                f"either set your password with `palaia-hub oauth set-password` "
                f"or configure a sign-in provider (`oauth.idp`); or use "
                f"`mode: cloud`, where clients like claude.ai and ChatGPT "
                f"connect exactly the same way and the dashboard stays on your "
                f"own network."
            )
    return config
