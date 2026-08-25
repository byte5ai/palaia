"""SPEC-403: ``build_production_app`` wires one hub-wide messenger, shared
by the ``/mcp/messenger`` tool family and any profile with
``messenger: true`` — same "flag ahead of the service" wiring
``test_serve_directory_spec402.py`` established for the directory.

Also asserted here: the production messenger's inbox authorization really is
the *directory's* session secret, not a second credential — a handle
registered through the directory tools opens its own inbox through the
messenger tools on the same running hub, and a wrong secret does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastmcp import Client

from palaia_hub.config import load_config
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry

sys.path.insert(0, str(Path(__file__).parent / "auth"))
from _asgi_mcp_client import mcp_client_transport  # noqa: E402

BASE_URL = "https://testserver"


async def _registered_vault(home: Path, key: str) -> None:
    registry = VaultRegistry(home)
    await registry.create(key, home / "vaults" / key, purpose=f"{key} vault.")


@pytest.mark.anyio
async def test_hub_wide_messenger_is_mounted(tmp_path: Path) -> None:
    config = load_config(home=tmp_path)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/messenger/")
            async with Client(transport) as client:
                names = {t.name for t in await client.list_tools()}
        assert names == {
            "messenger_send",
            "messenger_check",
            "messenger_ack",
            "messenger_thread",
        }
    finally:
        await production.dynamic_gateway.aclose()
        assert production.messenger_store is not None
        production.messenger_store.close()
        assert production.directory_store is not None
        production.directory_store.close()


@pytest.mark.anyio
async def test_profile_with_messenger_true_shares_the_hub_wide_messenger(
    tmp_path: Path,
) -> None:
    await _registered_vault(tmp_path, "work")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      directory: true\n"
        "      messenger: true\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            profile_transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/default/"
            )
            async with Client(profile_transport) as profile:
                names = {t.name for t in await profile.list_tools()}
                assert "messenger_send" in names
                assert "directory_register" in names

                # Two sessions, one profile connection: register both, then
                # message from one to the other.
                first = await profile.call_tool(
                    "directory_register", {"scope": "sender"}
                )
                second = await profile.call_tool(
                    "directory_register", {"scope": "recipient"}
                )
                a_handle = first.structured_content["session"]["handle"]
                a_secret = first.structured_content["session_secret"]
                b_handle = second.structured_content["session"]["handle"]
                b_secret = second.structured_content["session_secret"]

                sent = await profile.call_tool(
                    "messenger_send",
                    {
                        "handle": a_handle,
                        "session_secret": a_secret,
                        "to": b_handle,
                        "subject": "over the profile mount",
                        "message_type": "inform",
                        "body": "hello",
                    },
                )
                assert not sent.is_error

                # The wrong secret does not open B's inbox — the directory's
                # own credential is what the messenger checks.
                refused = await profile.call_tool(
                    "messenger_check",
                    {"handle": b_handle, "session_secret": a_secret},
                    raise_on_error=False,
                )
                assert refused.is_error

            # Read it back through the hub-wide mount: same store.
            messenger_transport = mcp_client_transport(
                production.app, f"{BASE_URL}/mcp/messenger/"
            )
            async with Client(messenger_transport) as messenger:
                arrived = await messenger.call_tool(
                    "messenger_check",
                    {"handle": b_handle, "session_secret": b_secret},
                )
        subjects = [e["subject"] for e in arrived.structured_content["envelopes"]]
        assert subjects == ["over the profile mount"]
    finally:
        await production.dynamic_gateway.aclose()
        assert production.messenger_store is not None
        production.messenger_store.close()
        assert production.directory_store is not None
        production.directory_store.close()
        for index in production.indexes.values():
            await index.close()


@pytest.mark.anyio
async def test_a_ref_is_validated_against_a_real_vault_index(tmp_path: Path) -> None:
    """Deliverable #1's ref validation, wired to the real thing: a note that
    exists in the hub's vault may be referenced; one that does not is
    refused."""
    await _registered_vault(tmp_path, "work")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\n"
        "auth_enabled: false\n"
        "gateway:\n"
        "  profiles:\n"
        "    - path: default\n"
        "      vaults: [work]\n"
        "      directory: true\n"
        "      messenger: true\n",
        encoding="utf-8",
    )
    config = load_config(home=tmp_path, create_if_missing=False)
    production = await build_production_app(config, home=tmp_path)
    try:
        async with production.app.router.lifespan_context(production.app):
            transport = mcp_client_transport(production.app, f"{BASE_URL}/mcp/default/")
            async with Client(transport) as client:
                written = await client.call_tool(
                    "work_memory_write",
                    {
                        "title": "Invoice model rename",
                        "body": "We renamed Bill to Invoice.",
                    },
                )
                assert not written.is_error
                permalink = written.structured_content["permalink"]

                first = await client.call_tool("directory_register", {"scope": "a"})
                second = await client.call_tool("directory_register", {"scope": "b"})
                a_handle = first.structured_content["session"]["handle"]
                a_secret = first.structured_content["session_secret"]
                b_handle = second.structured_content["session"]["handle"]

                good = await client.call_tool(
                    "messenger_send",
                    {
                        "handle": a_handle,
                        "session_secret": a_secret,
                        "to": b_handle,
                        "subject": "see the note",
                        "refs": [f"memory://{permalink}"],
                    },
                )
                bad = await client.call_tool(
                    "messenger_send",
                    {
                        "handle": a_handle,
                        "session_secret": a_secret,
                        "to": b_handle,
                        "subject": "see the note",
                        "refs": ["memory://does/not/exist"],
                    },
                    raise_on_error=False,
                )
        assert not good.is_error
        assert good.structured_content["envelopes"][0]["refs"] == [f"memory://{permalink}"]
        assert bad.is_error
        assert "memory://does/not/exist" in bad.content[0].text
    finally:
        await production.dynamic_gateway.aclose()
        assert production.messenger_store is not None
        production.messenger_store.close()
        assert production.directory_store is not None
        production.directory_store.close()
        for index in production.indexes.values():
            await index.close()
