"""Tool-ergonomics + acceptance tests for the messenger tool family
(SPEC-403) — the same treatment ``test_directory_tools.py`` gives the
directory: annotations-lint, alias absorption, dual text/json output, an
IDENTITY line distinguishing it from memory/stash/directory, plus every one
of the SPEC's own acceptance criteria driven through real
``fastmcp.Client`` sessions.

The headline test here is
``test_two_real_client_sessions_exchange_request_and_reply``: two separate
``fastmcp.Client`` connections, each registering itself through the SPEC-402
directory tools, exchanging a request and a reply over the messenger tools
and walking the resulting thread — the SPEC's first acceptance criterion,
end to end, with nothing stubbed between them but the hub.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastmcp import Client, FastMCP

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import DirectoryStore
from palaia_hub.gateway.directory_tools import build_directory_server
from palaia_hub.gateway.messenger_tools import (
    MESSENGER_TOOL_ACTIONS,
    build_messenger_server,
    render_envelopes,
)
from palaia_hub.messenger.models import (
    MAX_BODY_BYTES,
    MAX_BROADCAST_RECIPIENTS,
    Envelope,
)
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore


class _Clock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class _StubRefValidator:
    """Only ``memory://projects/api-gateway`` resolves."""

    def unresolvable(
        self, refs: list[str], *, readable_vaults: frozenset[str] | None = None
    ) -> list[str]:
        return [ref for ref in refs if ref != "memory://projects/api-gateway"]


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def directory(clock: _Clock) -> DirectoryService:
    return DirectoryService(DirectoryStore(":memory:", clock=clock))


@pytest.fixture
def messenger_store(clock: _Clock) -> Iterator[MessengerStore]:
    store = MessengerStore(":memory:", clock=clock)
    yield store
    store.close()


@pytest.fixture
def service(
    messenger_store: MessengerStore, directory: DirectoryService
) -> MessengerService:
    return MessengerService(
        messenger_store, directory, ref_validator=_StubRefValidator()
    )


@pytest.fixture
def server(service: MessengerService):  # noqa: ANN201 - fastmcp.FastMCP
    return build_messenger_server(service)


@pytest.fixture
def hub(service: MessengerService, directory: DirectoryService):  # noqa: ANN201
    """One profile carrying both families, exactly as a real profile with
    ``directory: true`` and ``messenger: true`` does — a session has to be
    able to register *and* message over one connection."""
    combined = FastMCP(name="palaia-test-profile")
    combined.mount(build_directory_server(directory))
    combined.mount(build_messenger_server(service))
    return combined


async def _register(client: Client, **fields: object) -> tuple[str, str]:
    result = await client.call_tool("directory_register", {"ttl_seconds": 600, **fields})
    assert not result.is_error
    return (
        result.structured_content["session"]["handle"],
        result.structured_content["session_secret"],
    )


# -- surface / ergonomics -----------------------------------------------------


@pytest.mark.anyio
async def test_every_action_is_exposed_as_a_tool(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == set(MESSENGER_TOOL_ACTIONS)


@pytest.mark.anyio
async def test_annotations_lint_every_tool_has_readonly_and_destructive_hints(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
    assert tools
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.readOnlyHint is not None, f"{tool.name} missing readOnlyHint"
        assert tool.annotations.destructiveHint is not None, f"{tool.name} missing destructiveHint"


@pytest.mark.anyio
async def test_check_is_not_readonly_because_it_marks_delivered(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert tools["messenger_check"].annotations.readOnlyHint is False
    assert tools["messenger_send"].annotations.readOnlyHint is False
    assert tools["messenger_ack"].annotations.readOnlyHint is False
    assert tools["messenger_thread"].annotations.readOnlyHint is True


@pytest.mark.anyio
async def test_server_instructions_carry_identity_and_distinguish_the_neighbours(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        init = client.initialize_result
    assert init is not None
    assert init.instructions is not None
    assert init.instructions.startswith("IDENTITY:")
    assert "NOT memory, NOT the stash and NOT the session directory" in init.instructions


@pytest.mark.anyio
async def test_every_tool_description_states_the_identity_and_the_body_rule(
    server,  # noqa: ANN001
) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.description is not None
        assert "NOT memory, NOT the stash and NOT the session directory" in tool.description
        assert "memory://" in tool.description


@pytest.mark.anyio
async def test_published_schema_shows_only_canonical_param_names(server) -> None:  # noqa: ANN001
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(tools["messenger_send"].inputSchema["properties"]) == {
        "handle",
        "session_secret",
        "to",
        "subject",
        "message_type",
        "body",
        "urgency",
        "expects_reply",
        "refs",
        "reply_to",
        "ttl_seconds",
    }
    assert set(tools["messenger_thread"].inputSchema["properties"]) == {
        "handle",
        "session_secret",
        "envelope_id",
    }


@pytest.mark.anyio
async def test_alias_absorption_from_type_text_and_id(hub) -> None:  # noqa: ANN001
    """``from``/``type``/``text``/``id`` are absorbed as aliases — a model
    that writes the envelope's own field names still gets through."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, b_secret = await _register(b)
        sent = await a.call_tool(
            "messenger_send",
            {
                "from": a_handle,
                "session_secret": a_secret,
                "recipient": b_handle,
                "subject": "aliased",
                "type": "question",
                "text": "does this work",
            },
        )
        assert not sent.is_error
        envelope_id = sent.structured_content["envelopes"][0]["id"]
        received = await b.call_tool(
            "messenger_check", {"handle": b_handle, "session_secret": b_secret}
        )
        acked = await b.call_tool(
            "messenger_ack",
            {"handle": b_handle, "session_secret": b_secret, "id": envelope_id},
        )
    assert received.structured_content["envelopes"][0]["type"] == "question"
    assert received.structured_content["envelopes"][0]["body"] == "does this work"
    assert acked.structured_content["state"] == "acked"


@pytest.mark.anyio
async def test_the_envelope_serializes_the_fixed_protocol_shape(hub) -> None:  # noqa: ANN001
    """The SPEC's envelope, verbatim — including ``from`` as the wire key."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, _ = await _register(b)
        sent = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "shape",
                "message_type": "inform",
            },
        )
    envelope = sent.structured_content["envelopes"][0]
    assert set(envelope) == {
        "id",
        "type",
        "from",
        "to",
        "subject",
        "urgency",
        "expects_reply",
        "body",
        "refs",
        "reply_to",
        "created_at",
        "expires_at",
    }
    assert envelope["from"] == a_handle
    assert envelope["to"] == b_handle


# -- the SPEC's acceptance criteria -------------------------------------------


@pytest.mark.anyio
async def test_two_real_client_sessions_exchange_request_and_reply(hub) -> None:  # noqa: ANN001
    """SPEC-403 acceptance #1: two real ``fastmcp.Client`` sessions
    (registered via SPEC-402) exchange request → reply e2e; the thread links
    via ``reply_to``."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a, scope="reviewing the billing service")
        b_handle, b_secret = await _register(b, scope="refactoring the billing service")

        # A finds B in the directory rather than being told the handle.
        found = await a.call_tool("directory_query", {"scope_contains": "refactoring"})
        assert [s["handle"] for s in found.structured_content["sessions"]] == [b_handle]

        request = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "rename the invoice model",
                "message_type": "request",
                "body": "it is called Bill everywhere else",
                "expects_reply": True,
                "urgency": "high",
                "refs": ["memory://projects/api-gateway"],
            },
        )
        assert not request.is_error
        request_id = request.structured_content["envelopes"][0]["id"]

        inbox = await b.call_tool(
            "messenger_check", {"handle": b_handle, "session_secret": b_secret}
        )
        assert not inbox.is_error
        arrived = inbox.structured_content["envelopes"]
        assert [envelope["id"] for envelope in arrived] == [request_id]
        assert arrived[0]["body"] == "it is called Bill everywhere else"
        assert arrived[0]["refs"] == ["memory://projects/api-gateway"]

        reply = await b.call_tool(
            "messenger_send",
            {
                "handle": b_handle,
                "session_secret": b_secret,
                "to": a_handle,
                "subject": "renamed",
                "message_type": "inform",
                "body": "done in 3 files",
                "reply_to": request_id,
            },
        )
        assert not reply.is_error
        reply_id = reply.structured_content["envelopes"][0]["id"]
        assert reply.structured_content["envelopes"][0]["reply_to"] == request_id

        back = await a.call_tool(
            "messenger_check", {"handle": a_handle, "session_secret": a_secret}
        )
        assert [envelope["id"] for envelope in back.structured_content["envelopes"]] == [
            reply_id
        ]

        thread = await a.call_tool(
            "messenger_thread",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "envelope_id": reply_id,
            },
        )
    assert not thread.is_error
    assert thread.structured_content["root_id"] == request_id
    assert [e["id"] for e in thread.structured_content["envelopes"]] == [
        request_id,
        reply_id,
    ]


@pytest.mark.anyio
async def test_a_5000_byte_body_is_refused_with_the_write_it_to_memory_message(
    hub,  # noqa: ANN001
) -> None:
    """SPEC-403 acceptance #2, first half."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, _ = await _register(b)
        result = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "too much",
                "body": "x" * 5000,
            },
            raise_on_error=False,
        )
    assert result.is_error
    message = result.content[0].text
    assert "5000" in message
    assert str(MAX_BODY_BYTES) in message
    assert "write it to memory and reference it" in message


@pytest.mark.anyio
async def test_a_ref_that_resolves_nowhere_is_refused(hub) -> None:  # noqa: ANN001
    """SPEC-403 acceptance #2, second half."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, _ = await _register(b)
        result = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "dangling",
                "refs": ["memory://nowhere/at/all"],
            },
            raise_on_error=False,
        )
    assert result.is_error
    assert "memory://nowhere/at/all" in result.content[0].text


@pytest.mark.anyio
async def test_session_a_cannot_check_session_bs_inbox(hub) -> None:  # noqa: ANN001
    """SPEC-403 acceptance #3: the session-secret test. A's own secret does
    not open B's inbox, and neither does a guessed one."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, b_secret = await _register(b)
        await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "for B only",
                "body": "confidential",
            },
        )

        with_as_secret = await a.call_tool(
            "messenger_check",
            {"handle": b_handle, "session_secret": a_secret},
            raise_on_error=False,
        )
        with_a_guess = await a.call_tool(
            "messenger_check",
            {"handle": b_handle, "session_secret": "guessed"},
            raise_on_error=False,
        )
        assert with_as_secret.is_error
        assert with_a_guess.is_error
        assert "confidential" not in with_as_secret.content[0].text
        assert "confidential" not in with_a_guess.content[0].text

        # B, with B's own secret, gets it.
        mine = await b.call_tool(
            "messenger_check", {"handle": b_handle, "session_secret": b_secret}
        )
    assert [e["subject"] for e in mine.structured_content["envelopes"]] == ["for B only"]


@pytest.mark.anyio
async def test_a_forged_sender_handle_is_refused(hub) -> None:  # noqa: ANN001
    """The other half of the same fence: A cannot send mail signed by B."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, _ = await _register(b)
        result = await a.call_tool(
            "messenger_send",
            {
                "handle": b_handle,
                "session_secret": a_secret,
                "to": a_handle,
                "subject": "signed by B",
            },
            raise_on_error=False,
        )
    assert result.is_error


@pytest.mark.anyio
async def test_broadcast_delivers_to_every_match_and_caps_at_twenty(hub) -> None:  # noqa: ANN001
    """SPEC-403 acceptance #4."""
    async with Client(hub) as sender:
        sender_handle, sender_secret = await _register(sender, scope="coordinating")
        peers: list[tuple[str, str]] = []
        async with Client(hub) as peer_client:
            for _ in range(3):
                peers.append(await _register(peer_client, scope="working on repo X"))

            sent = await sender.call_tool(
                "messenger_send",
                {
                    "handle": sender_handle,
                    "session_secret": sender_secret,
                    "to": "repo X",
                    "message_type": "broadcast",
                    "subject": "freeze main",
                },
            )
            assert not sent.is_error
            assert sorted(sent.structured_content["recipients"]) == sorted(
                handle for handle, _ in peers
            )
            for handle, secret in peers:
                arrived = await peer_client.call_tool(
                    "messenger_check", {"handle": handle, "session_secret": secret}
                )
                assert [e["subject"] for e in arrived.structured_content["envelopes"]] == [
                    "freeze main"
                ]

            # Push the match count one past the cap: refused, nothing sent.
            for _ in range(MAX_BROADCAST_RECIPIENTS + 1 - 3):
                await _register(peer_client, scope="working on repo X")
            over = await sender.call_tool(
                "messenger_send",
                {
                    "handle": sender_handle,
                    "session_secret": sender_secret,
                    "to": "repo X",
                    "message_type": "broadcast",
                    "subject": "too many",
                },
                raise_on_error=False,
            )
    assert over.is_error
    assert str(MAX_BROADCAST_RECIPIENTS) in over.content[0].text


@pytest.mark.anyio
async def test_an_unchecked_envelope_past_expires_at_is_gone(
    hub,  # noqa: ANN001
    clock: _Clock,
) -> None:
    """SPEC-403 acceptance #5, through the tools (clock-injectable)."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, b_secret = await _register(b)
        await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "short lived",
                "ttl_seconds": 120,
            },
        )
        clock.now += 121
        # Keep B's directory registration alive so the failure below can only
        # be the envelope's expiry, never a stale session.
        await b.call_tool(
            "directory_heartbeat", {"handle": b_handle, "session_secret": b_secret}
        )
        arrived = await b.call_tool(
            "messenger_check", {"handle": b_handle, "session_secret": b_secret}
        )
    assert arrived.structured_content["envelopes"] == []
    assert arrived.content[0].text == f"no new messages for {b_handle}"


@pytest.mark.anyio
async def test_an_unknown_or_stale_recipient_is_refused_in_plain_language(
    hub,  # noqa: ANN001
    clock: _Clock,
) -> None:
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, _ = await _register(b)

        unknown = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": "not-a-real-handle",
                "subject": "s",
            },
            raise_on_error=False,
        )
        assert unknown.is_error
        assert "directory_query" in unknown.content[0].text

        clock.now += 601  # past the 600s TTL both sessions registered with
        await a.call_tool(
            "directory_heartbeat", {"handle": a_handle, "session_secret": a_secret}
        )
        stale = await a.call_tool(
            "messenger_send",
            {
                "handle": a_handle,
                "session_secret": a_secret,
                "to": b_handle,
                "subject": "s",
            },
            raise_on_error=False,
        )
    assert stale.is_error
    assert "stale" in stale.content[0].text


# -- compact text rendering ---------------------------------------------------


def _envelope(**overrides: object) -> Envelope:
    fields: dict[str, object] = {
        "id": "e1",
        "type": "inform",
        "from_": "a",
        "to": "b",
        "subject": "the subject",
        "urgency": "normal",
        "expects_reply": False,
        "body": "the body text",
        "refs": [],
        "reply_to": None,
        "created_at": 0.0,
        "expires_at": 1.0,
    }
    fields.update(overrides)
    return Envelope.model_validate(fields)


def test_render_envelopes_shows_a_body_only_for_a_single_envelope() -> None:
    one = render_envelopes([_envelope()], empty="nothing")
    assert "the subject" in one
    assert "the body text" in one

    several = render_envelopes(
        [_envelope(id="e1"), _envelope(id="e2", subject="another")], empty="nothing"
    )
    assert "2 envelopes" in several
    assert "the subject" in several
    assert "another" in several
    assert "the body text" not in several


def test_render_envelopes_uses_the_callers_empty_line() -> None:
    assert render_envelopes([], empty="no new messages for x") == "no new messages for x"


def test_render_envelopes_names_refs_in_the_compact_line() -> None:
    text = render_envelopes(
        [
            _envelope(id="e1", refs=["memory://a"]),
            _envelope(id="e2", refs=["memory://b"]),
        ],
        empty="nothing",
    )
    assert "memory://a" in text
    assert "memory://b" in text


@pytest.mark.anyio
async def test_check_text_is_compact_for_several_envelopes(hub) -> None:  # noqa: ANN001
    """Token discipline in the text channel: several arrivals produce subject
    lines, not bodies — but every body is still in ``structured_content``."""
    async with Client(hub) as a, Client(hub) as b:
        a_handle, a_secret = await _register(a)
        b_handle, b_secret = await _register(b)
        for index in range(2):
            await a.call_tool(
                "messenger_send",
                {
                    "handle": a_handle,
                    "session_secret": a_secret,
                    "to": b_handle,
                    "subject": f"subject {index}",
                    "body": f"body-{index}-should-not-be-in-the-text",
                },
            )
        arrived = await b.call_tool(
            "messenger_check", {"handle": b_handle, "session_secret": b_secret}
        )
    text = arrived.content[0].text
    assert "subject 0" in text
    assert "subject 1" in text
    assert "should-not-be-in-the-text" not in text
    bodies = [e["body"] for e in arrived.structured_content["envelopes"]]
    assert bodies == [
        "body-0-should-not-be-in-the-text",
        "body-1-should-not-be-in-the-text",
    ]
