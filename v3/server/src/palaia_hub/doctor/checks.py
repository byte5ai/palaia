"""The checks the guided doctor ships with (issue #296).

Five of them, one per thing that can be wrong with a hub in a way the
owner can act on: its configuration, its vaults, its search, the clients
that connect to it, and the storage underneath all of that.

Every finding names its fix in the owner's terms. The three checks that can
repair something (:class:`VaultsCheck`, :class:`StorageCheck`) only ever do
what cannot lose data — clear a stale git lock, sweep crash residue,
rebuild the *disposable* index from the files, narrow a file's permissions.
Anything that would delete a client, a token or a note is reported with the
command spelled out and left for the owner to run.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from ..config import config_file_path, harden_config_file
from ..curator.wiring import TOKEN_ENV
from ..index import EmbedStatus, embed_progress
from ..oauth import now_seconds
from ..security.files import FILE_MODE
from ..vault.doctor import Finding as VaultFinding
from ..vault.doctor import VaultDoctor
from ..vault.engine import VaultEngine
from .context import DoctorContext
from .framework import Check, CheckSkipped, Finding, RepairOutcome

#: Values that look like they were copied out of the documentation and never
#: replaced. A hub configured with one of these is not configured.
_PLACEHOLDERS = ("example.com", "example.org", "example.net", "changeme", "yourdomain", "<")

#: Hosts that only mean anything on the machine the hub runs on — useless as
#: the address a phone or claude.ai gets redirected to.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

#: Vault findings :meth:`VaultDoctor.repair` is proven to fix (SPEC-003 Q5).
_SAFE_VAULT_REPAIRS = frozenset({"git-lock-stale", "orphan-temp-file"})

#: Warn below either of these — an absolute floor for small disks and a
#: share for large ones. A vault write is a git commit; a filesystem that
#: fills up turns every write into a failure.
LOW_DISK_BYTES = 1024**3
LOW_DISK_FRACTION = 0.05


def _contains_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _PLACEHOLDERS)


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


class ConfigCheck:
    """Does this hub's configuration say something it can actually do?

    Not a second copy of :class:`~palaia_hub.config.HubConfig`'s validators:
    those refuse a config outright (the hub will not start), so by the time
    the doctor runs they have all passed. What is left is the far larger
    class of settings that are *valid and wrong* — a public mode with no
    public address, an issuer still pointing at the documentation's example
    domain, a curator that is switched on but has no way to sign in.
    """

    id = "config"
    title = "Configuration"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        config = context.config
        findings: list[Finding] = []
        public_url = config.exposure.public_url
        issuer = config.oauth.issuer

        if config.mode in ("cloud", "open") and not public_url:
            findings.append(
                Finding(
                    code="public-address-missing",
                    severity="warning",
                    detail=(
                        f"mode {config.mode!r} exists to let clients reach this hub from "
                        f"outside your own network, but no public address is recorded, so "
                        f"the connect page cannot tell anyone what to connect to."
                    ),
                    fix=(
                        "Set `exposure.public_url` in config.yaml to the https address this "
                        "hub is reachable at, or run the dashboard's exposure wizard."
                    ),
                    subject="exposure.public_url",
                )
            )
        if public_url and not public_url.startswith("https://"):
            findings.append(
                Finding(
                    code="public-address-plaintext",
                    severity="error",
                    detail=(
                        f"exposure.public_url is {public_url!r}. claude.ai, ChatGPT and a "
                        f"phone all refuse a plaintext connection, so no remote client can "
                        f"use this hub at that address."
                    ),
                    fix=(
                        "Put the hub behind a tunnel or reverse proxy that terminates TLS "
                        "(Tailscale Funnel, cloudflared) and set `exposure.public_url` to "
                        "its https address."
                    ),
                    subject="exposure.public_url",
                )
            )
        for key, value in (("exposure.public_url", public_url), ("oauth.issuer", issuer)):
            if value and _contains_placeholder(value):
                findings.append(
                    Finding(
                        code="placeholder-value",
                        severity="warning",
                        detail=(
                            f"{key} is {value!r}, which still looks like the example from "
                            f"the documentation rather than this hub's own address."
                        ),
                        fix=f"Replace `{key}` in config.yaml with the address you actually use.",
                        subject=key,
                    )
                )
        if config.oauth.enabled and not issuer:
            findings.append(
                Finding(
                    code="oauth-issuer-missing",
                    severity="error",
                    detail=(
                        "the OAuth server is switched on but has no issuer, so it cannot "
                        "name itself in a token — the hub refuses to start like this."
                    ),
                    fix=(
                        "Set `oauth.issuer` in config.yaml to the public https URL clients "
                        "reach this hub at, or set `oauth.enabled: false` and use per-client "
                        "tokens instead."
                    ),
                    subject="oauth.issuer",
                )
            )
        if issuer and config.mode in ("cloud", "open") and _host_of(issuer) in _LOCAL_HOSTS:
            findings.append(
                Finding(
                    code="oauth-issuer-local",
                    severity="warning",
                    detail=(
                        f"oauth.issuer is {issuer!r}, an address that only means anything on "
                        f"the machine the hub runs on. A client signing in from anywhere "
                        f"else is redirected to its own computer and the sign-in fails."
                    ),
                    fix="Set `oauth.issuer` to the public https URL this hub is reachable at.",
                    subject="oauth.issuer",
                )
            )
        if config.mode == "locked" and config.host in ("0.0.0.0", "::"):
            findings.append(
                Finding(
                    code="bind-wider-than-mode",
                    severity="warning",
                    detail=(
                        f"mode is 'locked' — the mode for a hub only your own machines reach "
                        f"— but it listens on {config.host!r}, which is every network "
                        f"interface this box has, public ones included."
                    ),
                    fix=(
                        "Set `host` to 127.0.0.1 (or your tailnet address) in config.yaml; "
                        "or switch to `mode: cloud` if this hub really is meant to be "
                        "reachable from outside."
                    ),
                    subject="host",
                )
            )
        if config.curator.enabled and not (config.curator.token or os.environ.get(TOKEN_ENV)):
            findings.append(
                Finding(
                    code="curator-token-missing",
                    severity="warning",
                    detail=(
                        "the curator is switched on but has no token, so every curation run "
                        "fails to sign in to this hub and nothing in the inbox is filed."
                    ),
                    fix=(
                        f"Mint one with `palaia-hub curator token` and put it in the "
                        f"environment as {TOKEN_ENV}, or in `curator.token`."
                    ),
                    subject="curator.token",
                )
            )
        return findings


class VaultsCheck:
    """Vault integrity — files, git, identity, links, index drift.

    Thin on purpose: :class:`~palaia_hub.vault.doctor.VaultDoctor` already
    knows how to check one vault and how to repair it safely. This check's
    own work is the hub-level framing — running it per registered vault,
    saying which vault each finding is about, and collapsing the one finding
    class that can arrive by the thousand (file↔index drift reports one
    entry per note) into a single actionable line.
    """

    id = "vaults"
    title = "Vaults"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        if not context.vaults:
            return [
                Finding(
                    code="no-vaults",
                    severity="warning",
                    detail=(
                        "this hub has no vault registered, so there is nothing for a "
                        "connected client to remember into or recall from."
                    ),
                    fix=(
                        "Create one in the dashboard's setup wizard, or bring an existing "
                        "store over with `palaia-hub import v2 <path> --vault <dir>`."
                    ),
                )
            ]
        findings: list[Finding] = []
        for key, engine in sorted(context.vaults.items()):
            index = context.indexes.get(key)
            findings.extend(self._translate(key, await VaultDoctor(engine).verify(index)))
        return findings

    def _translate(self, key: str, vault_findings: Iterable[VaultFinding]) -> list[Finding]:
        drift: list[VaultFinding] = []
        out: list[Finding] = []
        for finding in vault_findings:
            if finding.code.startswith("index-"):
                drift.append(finding)
                continue
            out.append(
                Finding(
                    code=finding.code,
                    severity=finding.severity,
                    detail=finding.detail,
                    fix=finding.fix,
                    subject=f"{key}:{finding.path}" if finding.path else key,
                    repairable=finding.code in _SAFE_VAULT_REPAIRS,
                )
            )
        if drift:
            out.append(
                Finding(
                    code="index-drift",
                    severity="warning",
                    detail=(
                        f"{len(drift)} difference(s) between {key}'s files and its search "
                        f"index, so search answers from this vault are out of date. The "
                        f"files are intact — the index is the derived copy."
                    ),
                    fix=(
                        "Rebuild the index from the files — `palaia-hub doctor --fix` does "
                        "it, and so does starting the hub."
                    ),
                    subject=key,
                    repairable=True,
                )
            )
        return out

    async def repair(self, context: DoctorContext) -> Sequence[RepairOutcome]:
        outcomes: list[RepairOutcome] = []
        for key, engine in sorted(context.vaults.items()):
            for finding in await VaultDoctor(engine).repair():
                outcomes.append(
                    RepairOutcome(
                        check=self.id,
                        code=finding.code,
                        detail=finding.detail,
                        subject=key,
                        # A lock young enough to belong to a live git process
                        # is deliberately left alone, which is an outcome, not
                        # a success.
                        done=finding.code != "git-lock-held",
                    )
                )
            outcomes.extend(await self._rebuild_if_drifted(key, engine, context))
        return outcomes

    async def _rebuild_if_drifted(
        self, key: str, engine: VaultEngine, context: DoctorContext
    ) -> list[RepairOutcome]:
        """Rebuild ``key``'s index, but only if it actually drifted.

        Re-verifying here rather than trusting a report handed in from
        earlier keeps the repair idempotent and honest about *now*: a
        rebuild that was not needed is never reported as one that happened.
        """
        index = context.indexes.get(key)
        if index is None:
            return []
        verified = await VaultDoctor(engine).verify(index)
        drifted = [f for f in verified if f.code.startswith("index-")]
        if not drifted:
            return []
        count = await index.reindex()
        return [
            RepairOutcome(
                check=self.id,
                code="index-drift",
                detail=f"rebuilt the search index from the files ({count} note(s) indexed).",
                subject=key,
            )
        ]


class SearchCheck:
    """Is search actually usable — is there an index, and is it caught up?

    Separate from :class:`VaultsCheck` because the questions differ: that
    one asks whether the index agrees with the files, this one asks whether
    there is anything to ask in the first place, and how much of it can
    answer by meaning rather than by word.
    """

    id = "search"
    title = "Search"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        if not context.vaults:
            raise CheckSkipped("this hub has no vault yet, so there is no index to look at.")
        findings: list[Finding] = []
        for key in sorted(context.vaults):
            index = context.indexes.get(key)
            if index is None:
                findings.append(
                    Finding(
                        code="index-absent",
                        severity="warning",
                        detail=(
                            f"{key} has no search index yet, so recall and search find "
                            f"nothing in it — the notes themselves are untouched."
                        ),
                        fix=(
                            "Start the hub once; it builds the index from the files on "
                            "startup. Nothing needs to be re-imported."
                        ),
                        subject=key,
                    )
                )
                continue
            findings.extend(self._embed_findings(key, index.status().embeds))
        return findings

    def _embed_findings(self, key: str, embeds: EmbedStatus) -> list[Finding]:
        _, summary = embed_progress(embeds)
        findings: list[Finding] = []
        if not embeds.enabled:
            findings.append(
                Finding(
                    code="semantic-search-off",
                    severity="info",
                    detail=f"{key}: {summary}",
                    fix=(
                        "Full-text search works either way. To add meaning-based search, "
                        "install the hub's embeddings extra and turn embeddings on."
                    ),
                    subject=key,
                )
            )
        elif not embeds.available:
            findings.append(
                Finding(
                    code="semantic-search-unavailable",
                    severity="warning",
                    detail=f"{key}: {summary}",
                    fix=(
                        "Full-text search still answers every query. The line above names "
                        "the reason — usually a missing embeddings extra or a model that "
                        "never downloaded; fix that to get meaning-based search back."
                    ),
                    subject=key,
                )
            )
        elif embeds.pending:
            findings.append(
                Finding(
                    code="embed-backlog",
                    severity="info",
                    detail=f"{key}: {summary}",
                    fix="Nothing to do — the hub drains this in the background while it runs.",
                    subject=key,
                )
            )
        if embeds.failed:
            findings.append(
                Finding(
                    code="embed-failures",
                    severity="warning",
                    detail=(
                        f"{key}: {embeds.failed} passage(s) could not be embedded, so they "
                        f"are findable by word but not by meaning."
                    ),
                    fix=(
                        "Rebuild the index (`palaia-hub doctor --fix`) to retry them; if "
                        "they keep failing, the hub log names the model error."
                    ),
                    subject=key,
                )
            )
        return findings


class ClientsCheck:
    """Can anything connect, and is what connected still valid?"""

    id = "clients"
    title = "Connected clients"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        if context.tokens is None:
            raise CheckSkipped("no token store was opened for this pass.")
        findings = self._token_findings(context)
        findings.extend(self._oauth_findings(context))
        return findings

    def _token_findings(self, context: DoctorContext) -> list[Finding]:
        store = context.tokens
        assert store is not None  # guarded by run()
        config = context.config
        active = [info for info in store.list_tokens() if info.revoked_at is None]
        findings: list[Finding] = []
        if config.auth_enabled and not active and not config.oauth.enabled:
            findings.append(
                Finding(
                    code="no-way-in",
                    severity="warning",
                    detail=(
                        "this hub requires authentication but has no usable client token "
                        "and no OAuth server, so nothing can connect to it yet."
                    ),
                    fix=(
                        "Issue one on the dashboard's connect page, or with "
                        "`palaia-hub token create --name <client> --profile default`."
                    ),
                )
            )
        for info in active:
            # An unknown profile list (``None``) is not an empty one: without
            # it there is nothing to compare against, and guessing here would
            # condemn every token on a hub whose gateway shape simply could
            # not be resolved.
            if context.profiles and info.profile not in context.profiles:
                findings.append(
                    Finding(
                        code="token-unknown-profile",
                        severity="error",
                        detail=(
                            f"client {info.name!r} is bound to the profile "
                            f"{info.profile!r}, which this hub no longer serves — every "
                            f"call it makes is refused."
                        ),
                        fix=(
                            f"Bring that profile back in config.yaml's `gateway.profiles`, "
                            f"or revoke the token (`palaia-hub token revoke {info.id}`) and "
                            f"issue a new one for a profile that exists."
                        ),
                        subject=info.id,
                    )
                )
            elif context.live and info.last_used_at is None:
                findings.append(
                    Finding(
                        code="token-never-connected",
                        severity="info",
                        detail=(
                            f"client {info.name!r} has a token but has not connected since "
                            f"this hub last started."
                        ),
                        fix=(
                            "Finish that client's setup, or revoke the token with "
                            f"`palaia-hub token revoke {info.id}` if it is not needed."
                        ),
                        subject=info.id,
                    )
                )
        return findings

    def _oauth_findings(self, context: DoctorContext) -> list[Finding]:
        config = context.config
        if not config.oauth.enabled:
            return []
        store = context.oauth
        if store is None:
            return [
                Finding(
                    code="oauth-not-started",
                    severity="info",
                    detail=(
                        "the OAuth server is switched on, but this hub has never started "
                        "with it — no sign-ins or clients are recorded yet."
                    ),
                    fix="Start the hub; the OAuth database is created on first run.",
                )
            ]
        findings: list[Finding] = []
        if store.get_owner() is None and config.oauth.idp is None:
            findings.append(
                Finding(
                    code="oauth-no-owner",
                    severity="error",
                    detail=(
                        "the OAuth server is switched on but no owner account exists and no "
                        "identity provider is configured, so nobody can complete a sign-in."
                    ),
                    fix=(
                        "Create the owner account with "
                        "`palaia-hub oauth set-password --username <you>`, or configure an "
                        "identity provider under `oauth.idp`."
                    ),
                )
            )
        cutoff = now_seconds() - config.oauth.client_gc_ttl
        stale = [
            client
            for client in store.list_clients()
            if not client.is_machine and client.last_seen_at < cutoff
        ]
        if stale:
            days = round(config.oauth.client_gc_ttl / 86400)
            findings.append(
                Finding(
                    code="oauth-clients-stale",
                    severity="info",
                    detail=(
                        f"{len(stale)} registered client(s) have not been seen in over "
                        f"{days} day(s). They are leftovers from clients that were removed "
                        f"or re-registered."
                    ),
                    # Deliberately not a one-click repair: pruning makes those
                    # clients register again, which is the owner's call.
                    fix="Prune them when you are sure they are gone: `palaia-hub oauth gc`.",
                )
            )
        return findings


class StorageCheck:
    """The disk and the file permissions everything else depends on."""

    id = "storage"
    title = "Storage"

    async def run(self, context: DoctorContext) -> Sequence[Finding]:
        findings: list[Finding] = []
        if not os.access(context.home, os.W_OK):
            findings.append(
                Finding(
                    code="home-not-writable",
                    severity="error",
                    detail=(
                        f"{context.home} is not writable by this user, so the hub cannot "
                        f"save its configuration, tokens or vault registrations."
                    ),
                    fix=(
                        "Give this user ownership of that directory, or point PALAIA_HOME "
                        "at one it owns."
                    ),
                    subject=str(context.home),
                )
            )
        findings.extend(self._disk_findings(context))
        findings.extend(self._permission_findings(context))
        return findings

    def _filesystems(self, context: DoctorContext) -> list[Path]:
        """One representative path per distinct filesystem, in a stable order.

        Vaults may well live on another disk than the hub home — checking
        only one of them would miss exactly the disk that fills up.
        """
        seen: dict[int, Path] = {}
        candidates = [context.home, *(engine.root for engine in context.vaults.values())]
        for path in candidates:
            try:
                device = path.stat().st_dev
            except OSError:  # pragma: no cover - vanished under us
                continue
            seen.setdefault(device, path)
        return list(seen.values())

    def _disk_findings(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for path in self._filesystems(context):
            try:
                usage = shutil.disk_usage(path)
            except OSError:  # pragma: no cover - platform dependent
                continue
            if usage.free >= LOW_DISK_BYTES and usage.free >= usage.total * LOW_DISK_FRACTION:
                continue
            findings.append(
                Finding(
                    code="disk-space-low",
                    severity="warning",
                    detail=(
                        f"the disk holding {path} has {usage.free / 1e9:.1f} GB free of "
                        f"{usage.total / 1e9:.1f} GB. Every note the hub saves is a git "
                        f"commit, and those start failing when the disk fills."
                    ),
                    fix="Free space on that disk, or move the vault to a larger one.",
                    subject=str(path),
                )
            )
        return findings

    def _permission_findings(self, context: DoctorContext) -> list[Finding]:
        if os.name != "posix":  # pragma: no cover - POSIX modes only
            return []
        path = config_file_path(context.home)
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except OSError:
            return []
        if not mode & 0o077:
            return []
        return [
            Finding(
                code="config-readable-by-others",
                severity="warning",
                detail=(
                    f"{path} is mode {mode:04o}, so other accounts on this machine can read "
                    f"it — and it holds your identity provider's client secret and every "
                    f"address this hub answers at."
                ),
                fix=(
                    f"Narrow it to {FILE_MODE:04o} — `palaia-hub doctor --fix` does it, and "
                    f"so does `chmod 600 {path}`."
                ),
                subject=str(path),
                repairable=True,
            )
        ]

    async def repair(self, context: DoctorContext) -> Sequence[RepairOutcome]:
        outcomes: list[RepairOutcome] = []
        for finding in self._permission_findings(context):
            path = Path(finding.subject or config_file_path(context.home))
            harden_config_file(path)
            outcomes.append(
                RepairOutcome(
                    check=self.id,
                    code=finding.code,
                    detail=f"narrowed {path} to {FILE_MODE:04o} (owner-only).",
                    subject=str(path),
                )
            )
        return outcomes


def default_checks() -> tuple[Check, ...]:
    """Every check ``palaia-hub doctor`` runs, in report order."""
    return (ConfigCheck(), VaultsCheck(), SearchCheck(), ClientsCheck(), StorageCheck())


__all__ = [
    "LOW_DISK_BYTES",
    "LOW_DISK_FRACTION",
    "ClientsCheck",
    "ConfigCheck",
    "SearchCheck",
    "StorageCheck",
    "VaultsCheck",
    "default_checks",
]
