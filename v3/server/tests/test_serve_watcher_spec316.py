"""Issue #316: the production hub watches every vault for edits made outside it.

Before this, ``build_production_app`` opened an index per vault but never
started a :class:`~palaia_hub.vault.VaultWatcher`, so a note edited in
Obsidian (or written by ``palaia-hub import`` against a running hub) never
reached search until the next restart.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from palaia_hub.config import load_config
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

_LAG_BUDGET_SECONDS = 10.0


async def _wait_until_indexed(production: object, vault: str, needle: str, permalink: str) -> float:
    index = production.indexes[vault]  # type: ignore[attr-defined]
    started = time.monotonic()
    while time.monotonic() - started < _LAG_BUDGET_SECONDS:
        hits = await index.search(needle, mode="fts", limit=5)
        if any(hit.permalink == permalink for hit in hits.hits):
            return time.monotonic() - started
        await asyncio.sleep(0.05)
    raise AssertionError(f"external edit to {permalink!r} never reached the index")


def _external_note(vault_root: Path, name: str, title: str, body: str) -> None:
    target = vault_root / "notes" / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\ntitle: {title}\npermalink: notes/{name}\ntype: note\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_an_external_edit_to_a_startup_vault_is_indexed_live(tmp_path: Path) -> None:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        assert set(production.watchers) == {"work"}
        assert not production.watchers["work"].running  # the lifespan starts it
        async with production.app.router.lifespan_context(production.app):
            assert production.watchers["work"].running
            await asyncio.sleep(0.3)  # watchfiles has no "watch established" signal
            _external_note(
                tmp_path / "vaults" / "work",
                "written-outside",
                "Written Outside",
                "This body arrived from an external editor.",
            )
            await _wait_until_indexed(
                production, "work", "arrived from an external editor", "notes/written-outside"
            )
        # ...and the lifespan stops it again, before the indexes close.
        assert not production.watchers["work"].running
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


@pytest.mark.anyio
async def test_a_vault_created_through_the_wizard_gets_a_watcher_too(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            transport = httpx.ASGITransport(app=production.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                created = await c.post("/api/vaults", json={"key": "fresh", "purpose": "new."})
            assert created.status_code == 200, created.text
            assert "fresh" in production.watchers
            assert production.watchers["fresh"].running
            await asyncio.sleep(0.3)
            _external_note(
                tmp_path / "vaults" / "fresh",
                "dropped-in",
                "Dropped In",
                "Pasted into the folder by hand.",
            )
            await _wait_until_indexed(
                production, "fresh", "pasted into the folder", "notes/dropped-in"
            )
        assert not production.watchers["fresh"].running
    finally:
        await production.dynamic_gateway.aclose()
        _close(production)


def _close(production: object) -> None:
    for attribute in ("stash_store", "directory_store", "messenger_store"):
        store = getattr(production, attribute)
        if store is not None:
            store.close()
