"""Builds the messenger tool family as a mountable FastMCP server (SPEC-403
deliverable #3).

``messenger_send``/``messenger_check``/``messenger_ack``/
``messenger_thread``, following the patterns the stash
(:mod:`palaia_hub.gateway.stash_tools`) and directory
(:mod:`palaia_hub.gateway.directory_tools`) families already established —
consistency beats invention:

- **Behavior annotations** on every tool. Note ``messenger_check`` is *not*
  ``readOnlyHint``: it marks what it hands over as delivered, which is a
  state change a client must be allowed to see coming.
- **Alias absorption**: ``sender`` also accepts ``from``/``handle`` (``from``
  is a Python keyword, so it cannot be the parameter's own name — the
  *envelope* still serializes it as ``from``, which is the part the protocol
  fixed); ``to`` also accepts ``recipient``; ``message_type`` also accepts
  ``type``/``kind``; ``body`` also accepts ``text``/``message``.
- **Dual text/json output**, with the text rendering **compact by design**:
  subject + type + refs per envelope, and the body only when a result
  carries exactly one envelope. A session polling its inbox should pay for
  subject lines, not for every body it has not decided to read
  (:func:`render_envelopes`). Every body is always present in
  ``structured_content`` — the compaction is about the human/text channel,
  not about withholding anything from the caller.
- **Own IDENTITY line**, distinct from memory/stash/directory: this is a
  message *transport*, and its instructions say so up front, including the
  rule that makes it cheap — long content goes to memory once and travels
  as a ``memory://`` ref.

Like stash and the directory, this family is not namespaced by mount (there
is one messenger per hub), so the four tool names below are final;
:mod:`palaia_hub.gateway.build` mounts this server as-is.

**Every tool takes ``handle`` + ``session_secret``.** That is the SPEC-402
credential, reused (SPEC-403 deliverable #4) — not a second one. It is what
makes "session A cannot read session B's inbox" true no matter what scopes
A's token carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, Field
from starlette.types import ASGIApp

from ..auth.enforcement import missing_messenger_scope_error, readable_vaults_for_call
from ..messenger.models import (
    DEFAULT_TTL_SECONDS,
    MAX_BODY_BYTES,
    MAX_BROADCAST_RECIPIENTS,
    MAX_SUBJECT_CHARS,
    MAX_TTL_SECONDS,
    Envelope,
    MessageType,
    MessengerError,
    Urgency,
)
from ..messenger.service import MessengerService, envelope_summary

MESSENGER_TOOL_ACTIONS: tuple[str, ...] = (
    "messenger_send",
    "messenger_check",
    "messenger_ack",
    "messenger_thread",
)

MESSENGER_IDENTITY = (
    "IDENTITY: this is the messenger — typed messages between agent "
    "sessions, brokered by this hub. It is NOT memory, NOT the stash and "
    "NOT the session directory: it carries messages, it does not store "
    "knowledge, cache data or presence. Address peers by the handle they "
    "publish in the directory (directory_list/directory_query). Every call "
    "needs your own handle and session_secret from directory_register — "
    "nobody can read your inbox without it, and you cannot read theirs. "
    f"Bodies are capped at {MAX_BODY_BYTES} UTF-8 bytes on purpose: write "
    "long content to memory once and pass its memory:// permalink in refs "
    "instead of pasting it into a message. Delivery is pull — call "
    "messenger_check to collect what has arrived; nothing is pushed at you."
)

HandleParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("handle", "from", "sender", "me"),
        description="Your own session handle, from directory_register's result.",
    ),
]
SessionSecretParam = Annotated[
    str,
    Field(description="Your own session secret, from directory_register's result. Never shared."),
]
EnvelopeIdParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("envelope_id", "id", "message_id"),
        description="The envelope id, as messenger_check reported it.",
    ),
]


def _error_result(exc: MessengerError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _scope_error(action: str) -> ToolResult | None:
    message = missing_messenger_scope_error(action)
    return ToolResult(content=message, is_error=True) if message else None


def render_envelopes(envelopes: list[Envelope], *, empty: str) -> str:
    """The compact text rendering (SPEC-403 deliverable #3).

    * no envelopes → ``empty``, as given by the caller;
    * exactly one → its summary line **plus its body** — this is "the
      single-envelope read", the only place a body appears in the text
      channel;
    * several → a count and one summary line each, no bodies.

    The rule is a rule and not a heuristic: a caller that wants one body
    asks about one envelope (``messenger_thread`` on its id), and a caller
    polling an inbox gets subject lines it can triage without paying for
    prose it may never read.
    """
    if not envelopes:
        return empty
    if len(envelopes) == 1:
        envelope = envelopes[0]
        summary = f"{envelope.id} {envelope_summary(envelope)}"
        return f"{summary}\n\n{envelope.body}" if envelope.body else summary
    lines = [f"{len(envelopes)} envelopes:"]
    lines += [f"- {envelope.id} {envelope_summary(envelope)}" for envelope in envelopes]
    return "\n".join(lines)


def register_messenger_send_tool(server: FastMCP, service: MessengerService) -> None:
    """Register ``messenger_send`` on ``server``, backed by ``service``.

    Factored out of :func:`build_messenger_server` so a *second*,
    independent ``FastMCP`` instance — the session-monitor MCP App's own
    server (:mod:`palaia_hub.gateway.apps.team_app`, SPEC-405) — can carry a
    working compose action. That app's page calls back through the MCP Apps
    bridge (``app.callServerTool``), which only ever reaches a tool on the
    *same* server that served the calling page's ``ui://`` resource — it
    cannot reach across to this module's own ``/mcp/messenger`` mount. Both
    registrations call this exact function, so "compose from the team app"
    and "call messenger_send on ``/mcp/messenger`` directly" are the same
    tool running twice, not two implementations of one rule.
    """

    def desc(detail: str) -> str:
        return f"{MESSENGER_IDENTITY}\n\n{detail}"

    @server.tool(
        name="messenger_send",
        description=desc(
            "Send one typed message to another session. type is 'request', "
            "'inform', 'question', 'handoff' or 'broadcast'. For everything "
            "but 'broadcast', to is a session handle from the directory — an "
            "unknown or stale handle is refused. For 'broadcast', to is a "
            "directory query instead: '*' for every live session, "
            "'capability:<tag>' for a capability tag, or any substring of the "
            "scope you mean; it fans out to at most "
            f"{MAX_BROADCAST_RECIPIENTS} recipients and is refused (nothing "
            "sent) above that. Keep body short — the cap is "
            f"{MAX_BODY_BYTES} UTF-8 bytes; put long content in memory and "
            "pass its memory:// permalink in refs, which is validated to "
            "actually resolve. Set reply_to to an envelope id to answer it "
            "(that is what links a thread)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def messenger_send(
        handle: HandleParam,
        session_secret: SessionSecretParam,
        to: Annotated[
            str,
            Field(
                validation_alias=AliasChoices("to", "recipient"),
                description=(
                    "The recipient's session handle — or, for type='broadcast', "
                    "a directory query ('*', 'capability:<tag>', or a scope substring)."
                ),
            ),
        ],
        subject: Annotated[
            str,
            Field(
                description=(
                    "One line saying what this is about, at most "
                    f"{MAX_SUBJECT_CHARS} characters. Recipients route on this."
                )
            ),
        ],
        message_type: Annotated[
            MessageType,
            Field(
                validation_alias=AliasChoices("message_type", "type", "kind"),
                description=(
                    "request (asking for work), inform (no reply needed), question "
                    "(asking for an answer), handoff (passing work over), broadcast "
                    "(one query, many recipients)."
                ),
            ),
        ] = "inform",
        body: Annotated[
            str,
            Field(
                validation_alias=AliasChoices("body", "text", "message"),
                description=(
                    f"The message itself, at most {MAX_BODY_BYTES} UTF-8 bytes. "
                    "Anything longer belongs in memory, referenced from refs."
                ),
            ),
        ] = "",
        urgency: Annotated[Urgency, Field(description="'low', 'normal' or 'high'.")] = "normal",
        expects_reply: Annotated[
            bool,
            Field(description="True if you are waiting on an answer to this."),
        ] = False,
        refs: Annotated[
            list[str] | None,
            Field(
                description=(
                    "memory:// references into a vault you can read, e.g. "
                    "['memory://projects/api-gateway']. Each one is checked to "
                    "resolve; a dangling reference is refused."
                )
            ),
        ] = None,
        reply_to: Annotated[
            str | None,
            Field(description="The envelope id this answers, or unset for a new message."),
        ] = None,
        ttl_seconds: Annotated[
            float | None,
            Field(
                description=(
                    f"How long this stays deliverable. Default {DEFAULT_TTL_SECONDS:.0f}s "
                    f"(24h), maximum {MAX_TTL_SECONDS:.0f}s (7 days)."
                )
            ),
        ] = None,
    ) -> ToolResult:
        if (err := _scope_error("messenger_send")) is not None:
            return err
        try:
            result = await service.send(
                sender=handle,
                session_secret=session_secret,
                message_type=message_type,
                to=to,
                subject=subject,
                body=body,
                urgency=urgency,
                expects_reply=expects_reply,
                refs=refs,
                reply_to=reply_to,
                ttl_seconds=ttl_seconds,
                readable_vaults=readable_vaults_for_call(),
            )
        except MessengerError as exc:
            return _error_result(exc)
        if result.broadcast_query is not None:
            text = (
                f"broadcast {result.broadcast_query!r} sent to "
                f"{len(result.recipients)} session(s): {', '.join(result.recipients)}"
            )
        else:
            text = (
                f"sent {result.envelopes[0].id} to {result.recipients[0]} "
                f"({message_type}/{urgency})"
            )
        return ToolResult(content=text, structured_content=result)


def build_messenger_server(
    service: MessengerService, *, auth: AuthProvider | None = None
) -> FastMCP:
    """Build the messenger tool family, backed by ``service``."""
    server = FastMCP(name="palaia-messenger", instructions=MESSENGER_IDENTITY, auth=auth)

    def desc(detail: str) -> str:
        return f"{MESSENGER_IDENTITY}\n\n{detail}"

    register_messenger_send_tool(server, service)

    @server.tool(
        name="messenger_check",
        description=desc(
            "Collect every new envelope addressed to YOUR handle and mark it "
            "delivered. Requires your own handle and session_secret — this "
            "never reads another session's inbox. Delivery is pull: call this "
            "periodically (a heartbeat is a good moment). Already-delivered "
            "envelopes are not returned again; re-read one with "
            "messenger_thread on its id. The text summary is compact on "
            "purpose — bodies are in the structured result, and the text "
            "shows one only when a single envelope arrived."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def messenger_check(
        handle: HandleParam, session_secret: SessionSecretParam
    ) -> ToolResult:
        if (err := _scope_error("messenger_check")) is not None:
            return err
        try:
            result = await service.check(handle, session_secret)
        except MessengerError as exc:
            return _error_result(exc)
        text = render_envelopes(result.envelopes, empty=f"no new messages for {handle}")
        return ToolResult(content=text, structured_content=result)

    @server.tool(
        name="messenger_ack",
        description=desc(
            "Acknowledge and close one envelope in your own inbox — the "
            "sender's outbox then shows it as handled. Requires your own "
            "handle and session_secret; an id from somebody else's inbox is "
            "refused. Acking twice is harmless."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True),
    )
    async def messenger_ack(
        handle: HandleParam,
        session_secret: SessionSecretParam,
        envelope_id: EnvelopeIdParam,
    ) -> ToolResult:
        if (err := _scope_error("messenger_ack")) is not None:
            return err
        try:
            result = await service.ack(handle, session_secret, envelope_id)
        except MessengerError as exc:
            return _error_result(exc)
        return ToolResult(content=f"acked {result.id}", structured_content=result)

    @server.tool(
        name="messenger_thread",
        description=desc(
            "The whole reply chain an envelope belongs to, oldest first — "
            "walked through reply_to, narrowed to the envelopes you sent or "
            "received. Requires your own handle and session_secret. Use this "
            "to re-read a message you already collected, or to see what a "
            "conversation has covered before answering."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def messenger_thread(
        handle: HandleParam,
        session_secret: SessionSecretParam,
        envelope_id: EnvelopeIdParam,
    ) -> ToolResult:
        if (err := _scope_error("messenger_thread")) is not None:
            return err
        try:
            result = await service.thread(handle, session_secret, envelope_id)
        except MessengerError as exc:
            return _error_result(exc)
        text = render_envelopes(result.envelopes, empty=f"nothing in thread {envelope_id}")
        return ToolResult(content=text, structured_content=result)

    return server


@dataclass
class MessengerGatewayASGI:
    """The messenger server's mountable surface, mirroring
    :class:`palaia_hub.gateway.directory_tools.DirectoryGatewayASGI`'s shape
    for the one hub-level server this module builds. ``lifespan`` MUST be
    combined into whatever ASGI app ``app`` is mounted under, same caveat as
    stash and the directory.
    """

    app: ASGIApp
    lifespan: Any
    #: The ``FastMCP`` behind ``app`` — what
    #: :func:`palaia_hub.auth.policy.check_hub_mount_auth_policy` inspects.
    server: FastMCP


def build_messenger_gateway(
    service: MessengerService, *, auth: AuthProvider | None = None
) -> MessengerGatewayASGI:
    """Build the messenger server and its mountable ASGI app + lifespan,
    ready for ``app.mount("/mcp/messenger", ...)`` (see
    :mod:`palaia_hub.app`)."""
    server = build_messenger_server(service, auth=auth)
    asgi_app = server.http_app(path="/")
    return MessengerGatewayASGI(app=asgi_app, lifespan=asgi_app.lifespan, server=server)


__all__ = [
    "MESSENGER_IDENTITY",
    "MESSENGER_TOOL_ACTIONS",
    "MessengerGatewayASGI",
    "build_messenger_gateway",
    "build_messenger_server",
    "register_messenger_send_tool",
    "render_envelopes",
]
