"""Every file the hub persists is owner-only (SPEC-502 #2, acceptance #5).

The acceptance criterion asks for *one parametrized test* over every store,
and that shape is the point: a per-store test proves each store in isolation
and proves nothing about the store somebody adds next month. So this module
does two things instead.

1. :func:`test_every_store_file_is_owner_only` **exercises** every store
   into one hub home — creating a token, a hook, an automation, a stash
   entry, a session, a message, a notification, a secret, a queued webhook,
   a market entry, a vault index, a mode-audit line, ``config.yaml`` — and
   then walks the directory tree, asserting ``0600``/``0700`` on everything
   it finds. Nothing is enumerated by name, so a store added later is
   covered the day its first write lands in a hub home.
2. :func:`test_write_ahead_siblings_are_covered` pins the specific failure
   that motivated this: SQLite creates ``-wal``/``-shm`` under the process
   umask, carrying the same committed pages as the database, and narrowing
   only the database leaves them world-readable.

Skipped on platforms with no POSIX modes to assert.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from palaia_hub.auth.store import TokenStore
from palaia_hub.automations.models import NotificationAction
from palaia_hub.automations.outbox import AutomationOutbox
from palaia_hub.automations.store import AutomationStore
from palaia_hub.config import config_file_path, load_config
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.hooks.outbox import HookOutbox
from palaia_hub.hooks.store import HookStore
from palaia_hub.market.installed_store import InstalledAddonRecord, InstalledAddonStore
from palaia_hub.market.manual import ManualEntryStore
from palaia_hub.mcpb.signing import signing_cert_paths
from palaia_hub.messenger.store import MessengerStore
from palaia_hub.modes.audit import ModeAuditLog
from palaia_hub.notifications.store import NotificationStore
from palaia_hub.oauth.store import OAuthStore
from palaia_hub.registry.cache import DiskCache
from palaia_hub.security.files import DIR_MODE, FILE_MODE
from palaia_hub.stash.store import StashStore
from palaia_hub.upstream.secrets import SecretStore

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX file modes are not represented on Windows"
)

#: A umask that would leave every created file group- and world-readable.
#: Set for the duration of the exercise so the test proves the stores narrow
#: their own files rather than inheriting a tight umask from the runner.
_LOOSE_UMASK = 0o022


def _exercise_every_store(home: Path) -> None:
    """Touch every persistent store the hub has, in one home directory."""
    home.mkdir(parents=True, exist_ok=True)

    # config.yaml (holds an identity provider's client_secret when one is set)
    load_config(home)
    assert config_file_path(home).is_file()

    # SPEC-108 client tokens
    tokens = TokenStore(home)
    tokens.create("Codex on devbox", "default", ["vault:work:read"])

    # SPEC-201 webhooks + their outbox
    hooks = HookStore(home)
    created = hooks.create("https://example.test/hook", ["memory.entry.*"])
    outbox = HookOutbox(home / "hook-outbox.sqlite3")
    outbox.enqueue(
        hook_id=created.info.id,
        event_id="e1",
        event_name="memory.entry.created",
        payload=b'{"x":1}',
        signature="sha256=deadbeef",
    )
    outbox.close()

    # SPEC-307 automations + their outbox
    automations = AutomationStore(home)
    automations.create(
        name="notify",
        trigger_event="memory.entry.created",
        action=NotificationAction(title_template="new entry"),
    )
    automation_outbox = AutomationOutbox(home / "automations-outbox.sqlite3")
    automation_outbox.close()

    # SPEC-202 stash
    stash = StashStore(home / "stash.db")
    stash.set(namespace="team", key="handoff", value="secret payload")
    stash.close()

    # SPEC-402 session directory
    directory = DirectoryStore(home / "directory.db")
    directory.register(
        scope="team",
        host="devbox",
        platform="linux",
        agent_kind="codex",
        model="a-model",
    )
    directory.close()

    # SPEC-403 messenger
    messenger = MessengerStore(home / "messenger.db")
    messenger.close()

    # SPEC-307 notification centre
    notifications = NotificationStore(home / "notifications.sqlite3")
    notifications.create(title="hello", body="a body")
    notifications.close()

    # SPEC-302 encrypted secret store (database, key file, WAL siblings)
    secrets = SecretStore(home)
    secrets.put("upstream-api-key", "sk-not-a-real-key")
    secrets.close()

    # SPEC-203 authorization server state
    oauth = OAuthStore(home)
    oauth.open()
    oauth.close()

    # SPEC-303/304 marketplace caches
    manual = ManualEntryStore(home / "market_manual.sqlite3")
    manual.close()
    installed = InstalledAddonStore(home / "market_installed.json")
    installed.put(
        InstalledAddonRecord(
            upstream_key="fetch",
            entry_id="io.example/fetch",
            name="Fetch",
            kind="container",
            provenance="curated",
            installed_ref="ghcr.io/example/fetch:1",
            image="ghcr.io/example/fetch:1",
            container_name="palaia-addon-fetch",
            installed_at=0.0,
        )
    )
    DiskCache(home / "registry_cache").set("https://registry.test/servers", {"servers": []})

    # SPEC-205 mode-change audit log
    ModeAuditLog(home).record(
        from_mode="locked", to_mode="cloud", accepted=True, reason="", changed_keys=["mode"]
    )

    # SPEC-306 bundle-signing material (a private key and a public cert)
    signing_cert_paths(home)


#: The one file in a hub home that is allowed to be world-readable, and why.
#: It is the *public* half of the bundle-signing pair — the thing a verifier
#: is handed — and it sits inside a `0700` directory regardless. Written as
#: an exemption with a reason rather than by loosening the rule, so adding a
#: second one has to be argued for here.
PUBLIC_BY_DESIGN = {"mcpb/signing-cert.pem"}


def _offenders(home: Path) -> list[str]:
    bad: list[str] = []
    for path in sorted(home.rglob("*")):
        relative = path.relative_to(home).as_posix()
        if relative in PUBLIC_BY_DESIGN:
            continue
        mode = stat.S_IMODE(path.lstat().st_mode)
        expected = DIR_MODE if path.is_dir() else FILE_MODE
        if mode & 0o077:
            bad.append(f"{relative} is {mode:04o} (expected {expected:04o})")
    return bad


@pytest.fixture
def exercised_home(tmp_path: Path) -> Path:
    home = tmp_path / "palaia-home"
    previous = os.umask(_LOOSE_UMASK)
    try:
        _exercise_every_store(home)
    finally:
        os.umask(previous)
    return home


def test_the_exercise_actually_wrote_something(exercised_home: Path) -> None:
    """Guard the guard: an empty tree passes the audit trivially."""
    files = [p for p in exercised_home.rglob("*") if p.is_file()]
    assert len(files) >= 12, sorted(str(p.relative_to(exercised_home)) for p in files)


def test_every_store_file_is_owner_only(exercised_home: Path) -> None:
    assert _offenders(exercised_home) == []


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_write_ahead_siblings_are_covered(tmp_path: Path, suffix: str) -> None:
    """The specific gap SPEC-502 found: the WAL carries committed rows."""
    previous = os.umask(_LOOSE_UMASK)
    try:
        store = SecretStore(tmp_path)
        store.put("k", "v")
        sibling = (tmp_path / "secrets.sqlite3").with_name(f"secrets.sqlite3{suffix}")
        assert sibling.exists(), f"expected SQLite to have created {sibling.name}"
        assert stat.S_IMODE(sibling.stat().st_mode) & 0o077 == 0
        store.close()
    finally:
        os.umask(previous)


def test_a_widened_file_is_narrowed_again_on_the_next_open(tmp_path: Path) -> None:
    """`rsync -a` from a laxer box, or a manual chmod, does not stick."""
    store = SecretStore(tmp_path)
    store.put("k", "v")
    store.close()
    database = tmp_path / "secrets.sqlite3"
    database.chmod(0o644)

    reopened = SecretStore(tmp_path)
    try:
        assert stat.S_IMODE(database.stat().st_mode) == FILE_MODE
    finally:
        reopened.close()


def test_the_vault_index_database_is_owner_only(tmp_path: Path) -> None:
    """The index is derived data, but it holds every note's text verbatim.

    It lives inside the vault (``.palaia/``) rather than in the hub home, so
    the tree walk above never reaches it — hence its own case here.
    """
    import asyncio

    from palaia_hub.index import VaultIndex
    from palaia_hub.index.embeddings import EmbeddingConfig
    from palaia_hub.vault import EventBus, VaultEngine

    async def build() -> Path:
        engine = VaultEngine(tmp_path / "vault", "work", bus=EventBus())
        await engine.open(purpose="a test vault", create=True)
        index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
        await index.open(build=True, start_worker=False)
        path = index.db.path
        await index.close()
        await engine.close()
        return path

    previous = os.umask(_LOOSE_UMASK)
    try:
        database = asyncio.run(build())
    finally:
        os.umask(previous)

    assert database.is_file()
    assert stat.S_IMODE(database.stat().st_mode) == FILE_MODE
