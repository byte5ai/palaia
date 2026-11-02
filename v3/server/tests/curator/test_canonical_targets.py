"""The curator guards judge the note a call really changes (issue #603).

A note can be named many ways — permalink, title, alias, path, path suffix,
``memory://`` forms — and a folder can be spelled ``./inbox`` or ``/inbox/``.
Every equivalent reference to ``inbox/`` or an existing ``review/`` note must
share the same refusal, and leave the vault untouched. Real engine, real
curator profile, real fastmcp client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastmcp import Client

from palaia_hub.curator.policy import provenance_line
from palaia_hub.curator.profile import (
    CURATOR_PROFILE_PATH,
    curator_profile,
    curator_profile_middleware,
)
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine

CAPTURE_ID = "cap-1234567890"
PROVENANCE = provenance_line(CAPTURE_ID)


@dataclass
class Vault:
    engine: VaultEngine
    client: Client
    namespace: str
    capture: str  # the capture's path

    async def call(self, action: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        result = await self.client.call_tool(
            f"{self.namespace}_{action}", arguments, raise_on_error=False
        )
        return bool(result.is_error), result.content[0].text  # type: ignore[union-attr]

    async def text(self, path: str) -> str:
        await self.engine.refresh()
        return (await self.engine.read_note(path)).text

    async def snapshot(self) -> dict[str, str]:
        await self.engine.refresh()
        return {path: entry.checksum for path, entry in self.engine.catalog.items()}


@pytest.fixture
async def vault(engine: VaultEngine, vault_mount: VaultMountConfig) -> AsyncIterator[Vault]:
    service = EngineVaultService(engine)
    capture = await service.capture(
        what_it_concerns="Private capture", why_keep="Keep it", content="the raw input"
    )
    await engine.write_note(
        "review/pending-proposal.md",
        title="Pending proposal",
        body="Merge two notes.\n",
        frontmatter={"type": "proposal", "status": "proposed", "aliases": ["merge-plan"]},
    )
    await engine.write_note(
        "projects/api-gateway.md",
        title="API Gateway",
        body="The gateway.\n",
        frontmatter={"tags": ["infra", "gateway"]},
    )
    middleware = curator_profile_middleware([vault_mount], engines={vault_mount.key: engine})
    middleware[CURATOR_PROFILE_PATH][0].active_captures.acquire(CAPTURE_ID)  # type: ignore[attr-defined]
    gateway = build_gateway(
        GatewayConfig(vaults=[vault_mount], profiles=[curator_profile([vault_mount.key])]),
        {vault_mount.key: service},
        profile_middleware=middleware,
    )
    async with Client(gateway.profile_servers[CURATOR_PROFILE_PATH]) as client:
        path = engine.resolve(capture.permalink).path
        yield Vault(engine=engine, client=client, namespace=vault_mount.namespace, capture=path)


#: Every way to name the inbox capture (titled "Private capture").
CAPTURE_REFERENCES = [
    "inbox/private-capture",
    "inbox/private-capture.md",
    "Private capture",
    "private CAPTURE",
    "private-capture",
    "/inbox/private-capture",
    "memory://inbox/private-capture",
    "memory://work/inbox/private-capture",
]

#: Every way to name the existing review/ proposal.
PROPOSAL_REFERENCES = [
    "review/pending-proposal",
    "Pending proposal",
    "merge-plan",
    "pending-proposal",
    "memory://review/pending-proposal",
]

#: Every spelling of the inbox folder a write can carry.
INBOX_FOLDERS = [
    ("folder", "inbox"),
    ("folder", "./inbox"),
    ("folder", "/inbox/"),
    ("folder", "inbox/./"),
    ("folder", "./inbox/2026"),
    ("folder", ".\\inbox"),
    ("folder", "memory://inbox"),
    ("dir", "./inbox"),
    ("path", "inbox//2026"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("reference", CAPTURE_REFERENCES)
async def test_every_name_for_an_inbox_capture_is_refused(vault: Vault, reference: str) -> None:
    before = await vault.text(vault.capture)
    is_error, text = await vault.call(
        "edit", {"permalink": reference, "append": f"- [note] curated\n{PROVENANCE}"}
    )
    assert is_error
    assert "never edits inbox/" in text
    assert await vault.text(vault.capture) == before


@pytest.mark.anyio
@pytest.mark.parametrize("reference", PROPOSAL_REFERENCES)
async def test_every_name_for_an_existing_proposal_is_refused(vault: Vault, reference: str) -> None:
    before = await vault.text("review/pending-proposal.md")
    is_error, text = await vault.call(
        "edit", {"permalink": reference, "append": f"- [note] approved\n{PROVENANCE}"}
    )
    assert is_error
    assert "never edit existing ones" in text
    assert await vault.text("review/pending-proposal.md") == before


@pytest.mark.anyio
@pytest.mark.parametrize(("argument", "folder"), INBOX_FOLDERS)
async def test_every_spelling_of_inbox_is_refused_for_a_write(
    vault: Vault, argument: str, folder: str
) -> None:
    before = await vault.snapshot()
    is_error, text = await vault.call(
        "write", {"title": "Sneaky note", "body": PROVENANCE, argument: folder}
    )
    assert is_error
    assert "never writes into inbox/" in text
    assert await vault.snapshot() == before


@pytest.mark.anyio
async def test_an_ordinary_note_named_by_title_is_still_editable(vault: Vault) -> None:
    """The control: resolving targets refuses the reserved folders, nothing else."""
    is_error, _text = await vault.call(
        "edit", {"permalink": "API Gateway", "append": f"- [limit] 100\n{PROVENANCE}"}
    )
    assert not is_error
    assert PROVENANCE in await vault.text("projects/api-gateway.md")


@pytest.mark.anyio
async def test_a_write_lands_where_the_guard_judged_it(vault: Vault) -> None:
    is_error, _text = await vault.call(
        "write", {"title": "Ingest limit", "body": PROVENANCE, "folder": "./projects//"}
    )
    assert not is_error
    assert PROVENANCE in await vault.text("projects/ingest-limit.md")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tags",
    [[], ["infra"], ["gateway"], ["INFRA"]],
    ids=["erase all", "drop gateway", "drop infra", "drop gateway, case only"],
)
async def test_an_edit_may_not_remove_tags(vault: Vault, tags: list[str]) -> None:
    before = await vault.text("projects/api-gateway.md")
    is_error, text = await vault.call(
        "edit",
        {"permalink": "API Gateway", "append": f"- [note] x\n{PROVENANCE}", "tags": tags},
    )
    assert is_error
    assert "only adds" in text
    assert await vault.text("projects/api-gateway.md") == before


@pytest.mark.anyio
async def test_an_edit_may_add_tags(vault: Vault) -> None:
    is_error, _text = await vault.call(
        "edit",
        {
            "permalink": "API Gateway",
            "append": f"- [note] x\n{PROVENANCE}",
            "tags": ["Infra", "gateway", "rate-limit"],
        },
    )
    assert not is_error
    note = await vault.engine.read_note("projects/api-gateway.md")
    # Tags compare lowercase, as the vault reads them (format spec §2.1).
    assert {tag.lower() for tag in note.frontmatter["tags"]} == {"infra", "gateway", "rate-limit"}
