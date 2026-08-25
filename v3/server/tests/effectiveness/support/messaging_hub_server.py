"""Hub process for the SPEC-404 messaging effectiveness harness — same shape
as SPEC-207's ``hub_server.py``, mounting the session directory and
messenger tool families (SPEC-402/403) instead of (or alongside) the vault.

Two profiles, following the real gateway's own opt-in shape
(:class:`palaia_hub.gateway.config.ProfileConfig`):

- ``default`` — the vault's memory tools, exactly like the SPEC-207 hub,
  mounted only when ``--vault-dir`` is given (session A's probe needs a
  place to write the note it hands off a reference to; session B's probe
  does not, and omitting it keeps that probe's tool surface to exactly
  what the messenger skill is being measured against).
- ``messaging`` — ``directory_*`` + ``messenger_*``, always mounted.

Recording happens by subclassing :class:`DirectoryService`/
:class:`MessengerService` and overriding exactly the methods the gateway
tool wrappers call through (:mod:`palaia_hub.gateway.directory_tools`,
:mod:`palaia_hub.gateway.messenger_tools`) — the same boundary SPEC-207's
``RecordingService`` records the vault at, and for the same reason: a line
in the log means a tool body ran with those arguments, independent of how
any particular client formats its transcript.

``--seed-peer-scope`` registers one stand-in session *before* the agent's
own session starts, on a service instance the recording subclasses never
see — so the harness's own setup never shows up as a call the agent made.
The agent has to find that peer the same way it would find a real one: by
calling ``directory_list``/``directory_query``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import uvicorn

from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.messenger.models import AckResult, CheckResult, SendResult, ThreadResult
from palaia_hub.messenger.refs import build_vault_ref_validator
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore
from palaia_hub.vault import EventBus, VaultEngine, VaultWatcher

logger = logging.getLogger("effectiveness.messaging_hub_server")


class _Recorder:
    """Shared JSONL append, used by both recording subclasses below."""

    def __init__(self, log_path: Path) -> None:
        self._log_path = log_path

    def record(self, tool: str, **arguments: Any) -> None:
        line = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False, default=str)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class RecordingDirectoryService(DirectoryService):
    """:class:`DirectoryService`, recording every call the ``directory_*``
    tool family actually makes through it.

    Deliberately a subclass, not a hand-rolled duck type: ``build_gateway``
    and ``create_app`` both type this parameter as ``DirectoryService``, and
    a subclass is the one way to satisfy that *and* stay a real
    ``DirectoryService`` for ``.publish`` assignment and for
    :class:`MessengerService`'s own use of it as the session directory.
    """

    def __init__(self, store: DirectoryStore, recorder: _Recorder) -> None:
        super().__init__(store)
        self._recorder = recorder

    async def register(self, **kwargs: Any) -> Any:  # noqa: ANN401 - passthrough
        self._recorder.record("directory_register", **kwargs)
        return await super().register(**kwargs)

    async def heartbeat(self, handle: str, session_secret: str) -> Any:
        self._recorder.record("directory_heartbeat", handle=handle)
        return await super().heartbeat(handle, session_secret)

    async def update(self, handle: str, session_secret: str, **kwargs: Any) -> Any:
        self._recorder.record("directory_update", handle=handle, **kwargs)
        return await super().update(handle, session_secret, **kwargs)

    async def deregister(self, handle: str, session_secret: str) -> Any:
        self._recorder.record("directory_deregister", handle=handle)
        return await super().deregister(handle, session_secret)

    async def list(self, **kwargs: Any) -> Any:
        self._recorder.record("directory_list", **kwargs)
        return await super().list(**kwargs)

    async def query(self, **kwargs: Any) -> Any:
        self._recorder.record("directory_query", **kwargs)
        return await super().query(**kwargs)


class RecordingMessengerService(MessengerService):
    """:class:`MessengerService`, recording every call the ``messenger_*``
    tool family actually makes through it. Same reasoning as
    :class:`RecordingDirectoryService` above for why this is a subclass.
    """

    def __init__(self, *args: Any, recorder: _Recorder, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._recorder = recorder

    async def send(self, **kwargs: Any) -> SendResult:
        shown = {k: v for k, v in kwargs.items() if k != "session_secret"}
        self._recorder.record("messenger_send", **shown)
        return await super().send(**kwargs)

    async def check(self, handle: str, session_secret: str) -> CheckResult:
        self._recorder.record("messenger_check", handle=handle)
        return await super().check(handle, session_secret)

    async def ack(self, handle: str, session_secret: str, envelope_id: str) -> AckResult:
        self._recorder.record("messenger_ack", handle=handle, envelope_id=envelope_id)
        return await super().ack(handle, session_secret, envelope_id)

    async def thread(self, handle: str, session_secret: str, envelope_id: str) -> ThreadResult:
        self._recorder.record("messenger_thread", handle=handle, envelope_id=envelope_id)
        return await super().thread(handle, session_secret, envelope_id)


async def _run(
    *,
    host: str,
    port: int,
    record_path: Path,
    vault_dir: Path | None,
    vault_key: str,
    vault_name: str,
    purpose: str,
    seed_peer_scope: str | None,
) -> None:
    recorder = _Recorder(record_path)

    directory_store = DirectoryStore(":memory:")
    # A plain, unwrapped facade over the same store — used ONLY for the
    # harness's own setup below, so seeding never shows up in the log as a
    # call the agent made.
    setup_directory = DirectoryService(directory_store)
    directory_service = RecordingDirectoryService(directory_store, recorder)

    if seed_peer_scope:
        await setup_directory.register(
            scope=seed_peer_scope,
            host="peer-host",
            platform="other-tool",
            agent_kind="coding assistant",
        )

    indexes: dict[str, VaultIndex] = {}
    vault_services: dict[str, Any] = {}
    profiles = [
        ProfileConfig(path="messaging", vaults=[], directory=True, messenger=True),
    ]
    watcher: VaultWatcher | None = None
    engine: VaultEngine | None = None
    index: VaultIndex | None = None
    if vault_dir is not None:
        engine = VaultEngine(vault_dir, vault_name, bus=EventBus())
        await engine.open(purpose=purpose, create=True)
        index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
        await index.open()
        watcher = VaultWatcher(engine)
        await watcher.start()
        indexes[vault_key] = index
        vault_services[vault_key] = EngineVaultService(engine, index)
        profiles.append(
            ProfileConfig(path="default", vaults=[vault_key])
        )

    messenger_store = MessengerStore(":memory:")
    messenger_service = RecordingMessengerService(
        messenger_store,
        directory_service,
        ref_validator=build_vault_ref_validator(indexes),
        recorder=recorder,
    )

    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key=vault_key, name=vault_name, purpose=purpose)]
        if vault_dir is not None
        else [],
        profiles=profiles,
    )
    gateway = build_gateway(
        gateway_config,
        vault_services,
        directory_service=directory_service,
        messenger_service=messenger_service,
    )
    app = create_app(HubConfig(log_level="info"), gateway=gateway)

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    try:
        await server.serve()
    finally:
        if watcher is not None:
            await watcher.stop()
        if index is not None:
            await index.close()
        if engine is not None:
            await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--record", required=True, help="JSONL file every tool call is appended to")
    parser.add_argument(
        "--vault-dir", default=None, help="mount a 'default' vault profile from this directory"
    )
    parser.add_argument("--vault-key", default="work")
    parser.add_argument("--vault-name", default="work")
    parser.add_argument(
        "--purpose",
        default=(
            "Work knowledge: projects, decisions and how this team does things. "
            "Read it before deciding; add to it when something is worth keeping."
        ),
    )
    parser.add_argument(
        "--seed-peer-scope",
        default=None,
        help="pre-register one stand-in session with this scope, before the agent connects",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        _run(
            host=args.host,
            port=args.port,
            record_path=Path(args.record),
            vault_dir=Path(args.vault_dir) if args.vault_dir else None,
            vault_key=args.vault_key,
            vault_name=args.vault_name,
            purpose=args.purpose,
            seed_peer_scope=args.seed_peer_scope,
        )
    )


if __name__ == "__main__":
    main()
