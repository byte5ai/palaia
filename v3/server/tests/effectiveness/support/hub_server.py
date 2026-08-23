"""Hub process for the SPEC-207 effectiveness harness — same shape as
SPEC-113's ``e2e/support/hub_server.py``, plus a call recorder.

Why a second script rather than a flag on the e2e one: that script backs the
Phase-1 exit-criterion scenarios and nothing in this SPEC should be able to
change how those run. This one differs in exactly one way — every call the
memory tools make into the vault is appended to a JSONL file before it is
served — and that recording is the whole point here.

Recording happens at the ``VaultService`` boundary (:class:`RecordingService`)
rather than in MCP middleware. That boundary is the one the tools in
``palaia_hub.gateway.memory_tools`` actually call through, so a line in the
log means a tool body ran with those arguments: ground truth about agent
behaviour that does not depend on how a particular client formats its
transcript, or on FastMCP internals. Tool names as the *client* sees them
carry the vault namespace (``work_memory_recall``); the recorded ``tool``
field is the base action (``recall``), which is what the log's readers care
about.

Embeddings are off, for the reason SPEC-113 gives: a model download per run,
buying nothing these runs assert.
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
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.gateway.vault_protocol import (
    CaptureResult,
    InboxStatusResult,
    NoteRecord,
    NoteSummary,
    SearchHit,
    VaultService,
)
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.index import EmbeddingConfig, VaultIndex
from palaia_hub.recall.models import ContextResult, RecallResult
from palaia_hub.vault import EventBus, VaultEngine, VaultWatcher

logger = logging.getLogger("effectiveness.hub_server")


class RecordingService:
    """Delegating :class:`VaultService` that appends every call to a JSONL file.

    Written out method by method instead of with ``__getattr__`` so that a
    method added to the protocol later shows up as a type error here rather
    than as a silently unrecorded tool — the log is evidence, and evidence
    with a silent hole in it is worse than no evidence.
    """

    def __init__(self, inner: VaultService, log_path: Path) -> None:
        self._inner = inner
        self._log_path = log_path

    def _record(self, tool: str, **arguments: Any) -> None:
        line = json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False, default=str)
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    async def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        self._record("search", query=query, limit=limit)
        return await self._inner.search(query, limit=limit)

    async def read(self, permalink: str) -> NoteRecord:
        self._record("read", permalink=permalink)
        return await self._inner.read(permalink)

    async def write(
        self,
        title: str,
        body: str,
        *,
        folder: str = "",
        type: str = "note",  # noqa: A002 - matches the vault-format field name
        tags: list[str] | None = None,
    ) -> NoteRecord:
        self._record("write", title=title, body=body, folder=folder, type=type, tags=tags)
        return await self._inner.write(title, body, folder=folder, type=type, tags=tags)

    async def edit(
        self,
        permalink: str,
        *,
        body: str | None = None,
        append: str | None = None,
        tags: list[str] | None = None,
    ) -> NoteRecord:
        self._record("edit", permalink=permalink, body=body, append=append, tags=tags)
        return await self._inner.edit(permalink, body=body, append=append, tags=tags)

    async def move(self, permalink: str, folder: str) -> NoteRecord:
        self._record("move", permalink=permalink, folder=folder)
        return await self._inner.move(permalink, folder)

    async def delete(self, permalink: str) -> bool:
        self._record("delete", permalink=permalink)
        return await self._inner.delete(permalink)

    async def list_notes(self, *, folder: str = "") -> list[NoteSummary]:
        self._record("list", folder=folder)
        return await self._inner.list_notes(folder=folder)

    async def recent_activity(self, *, limit: int = 10) -> list[NoteSummary]:
        self._record("recent_activity", limit=limit)
        return await self._inner.recent_activity(limit=limit)

    async def capture(
        self,
        *,
        what_it_concerns: str,
        why_keep: str,
        content: str,
        source: str | None = None,
    ) -> CaptureResult:
        self._record(
            "capture",
            what_it_concerns=what_it_concerns,
            why_keep=why_keep,
            content=content,
            source=source,
        )
        return await self._inner.capture(
            what_it_concerns=what_it_concerns,
            why_keep=why_keep,
            content=content,
            source=source,
        )

    async def inbox_status(self) -> InboxStatusResult:
        self._record("inbox_status")
        return await self._inner.inbox_status()

    async def recall(
        self, *, query: str = "", ref: str = "", limit: int = 5, model: str = ""
    ) -> RecallResult:
        self._record("recall", query=query, ref=ref, limit=limit, model=model)
        return await self._inner.recall(query=query, ref=ref, limit=limit, model=model)

    async def build_context(
        self,
        *,
        ref: str = "",
        query: str = "",
        depth: int = 2,
        timeframe: str = "",
        max_tokens: int = 4000,
        model: str = "",
    ) -> ContextResult:
        self._record(
            "build_context",
            ref=ref,
            query=query,
            depth=depth,
            timeframe=timeframe,
            max_tokens=max_tokens,
            model=model,
        )
        return await self._inner.build_context(
            ref=ref,
            query=query,
            depth=depth,
            timeframe=timeframe,
            max_tokens=max_tokens,
            model=model,
        )


async def _run(
    *,
    host: str,
    port: int,
    vault_dir: Path,
    vault_key: str,
    vault_name: str,
    purpose: str,
    profile: str,
    record_path: Path,
) -> None:
    engine = VaultEngine(vault_dir, vault_name, bus=EventBus())
    await engine.open(purpose=purpose, create=True)
    index = VaultIndex(engine, embedding=EmbeddingConfig(enabled=False))
    await index.open()
    watcher = VaultWatcher(engine)
    await watcher.start()

    service = RecordingService(EngineVaultService(engine, index), record_path)
    gateway_config = GatewayConfig(
        vaults=[VaultMountConfig(key=vault_key, name=vault_name, purpose=purpose)],
        profiles=[ProfileConfig(path=profile, vaults=[vault_key])],
    )
    gateway = build_gateway(gateway_config, {vault_key: service})
    app = create_app(HubConfig(log_level="info"), gateway=gateway)

    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    try:
        await server.serve()
    finally:
        await watcher.stop()
        await index.close()
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--vault-dir", required=True)
    parser.add_argument("--vault-key", default="work")
    parser.add_argument("--vault-name", default="work")
    parser.add_argument(
        "--purpose",
        default=(
            "Work knowledge: projects, decisions and how this team does things. "
            "Read it before deciding; add to it when something is worth keeping."
        ),
    )
    parser.add_argument("--profile", default="default")
    parser.add_argument("--record", required=True, help="JSONL file every tool call is appended to")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        _run(
            host=args.host,
            port=args.port,
            vault_dir=Path(args.vault_dir),
            vault_key=args.vault_key,
            vault_name=args.vault_name,
            purpose=args.purpose,
            profile=args.profile,
            record_path=Path(args.record),
        )
    )


if __name__ == "__main__":
    main()
