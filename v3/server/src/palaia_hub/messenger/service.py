"""Async facade over :class:`MessengerStore`: authorization, addressing,
ref validation, ``message.*`` events (SPEC-403 deliverables #3–#5).

Same shape as :class:`palaia_hub.directory.service.DirectoryService` — the
gateway tool family and the REST mirror both call this, never the store, so
there is exactly one place that turns a lock-guarded SQLite call into an
``asyncio.to_thread`` call and publishes the resulting event.

**Where authorization lives.** Two different questions, answered in two
different places, deliberately:

* *May this client use the messenger at all?* — a token scope
  (``messenger:send`` / ``messenger:read``), checked in the tool wrapper
  (:mod:`palaia_hub.gateway.messenger_tools`) before any call reaches here.
* *Is this caller who they say they are?* — the **SPEC-402 session
  secret**, checked here, on every single call. No second credential is
  minted: the directory already issues exactly one secret per session, and
  the messenger reuses it. This is the SPEC's deliverable #4 in one
  sentence: *a scope alone must not read another session's inbox*, because
  a scope says what a client may do and only the secret says which session
  it is.

Both sides of every call are fenced by that secret:

* ``send`` proves the ``from`` handle. Without this the sender field would
  be pure self-assertion and any client with the scope could write mail
  signed by somebody else. (The SPEC names the scope as the requirement for
  sending; proving the sender handle is an *addition* on top of it, not a
  replacement — see the PR notes.)
* ``check``/``ack``/``thread`` prove the reader, and every one of them is
  additionally narrowed to rows where the caller is the recipient (``ack``)
  or a participant (``thread``). An id from somebody else's inbox is
  refused with :class:`~palaia_hub.messenger.models.NotYourEnvelopeError`,
  not answered.

**Events never carry a body.** All three (`message.sent`,
`message.received`, `message.expired`) are published from
:meth:`~palaia_hub.messenger.models.EnvelopeMetadata.of`, the one shape
that has no body field at all — so the SPEC's contract ("carrying envelope
metadata, never the body") is a property of a class rather than a rule
every call site has to remember.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from ..directory.models import (
    DirectoryError,
    QueryResult,
    SessionRecord,
)
from .models import (
    MAX_BROADCAST_RECIPIENTS,
    OWNER_HANDLE,
    AckResult,
    BroadcastError,
    CheckResult,
    DeliveryState,
    EndConversationResult,
    Envelope,
    EnvelopeDetailResult,
    EnvelopeMetadata,
    EnvelopeNotFoundError,
    FlowsResult,
    InboxItem,
    InvalidEnvelopeError,
    MessageType,
    NotYourEnvelopeError,
    RefValidator,
    SendResult,
    SessionAuthError,
    StaleRecipientError,
    ThreadMetadataResult,
    ThreadResult,
    UnknownRecipientError,
    UnresolvableRefError,
    Urgency,
    broadcast_query,
    check_refs,
)
from .store import DEFAULT_FLOW_LIMIT, MessengerStore

Publisher = Callable[[str, dict[str, Any]], None]


class SessionLookup(Protocol):
    """What the messenger needs of the SPEC-402 directory.

    A protocol, not the concrete
    :class:`~palaia_hub.directory.service.DirectoryService`, for the same
    reason :class:`~palaia_hub.messenger.models.RefValidator` is one: the
    real thing is passed in production, a small fake in a unit test, and
    the messenger states its requirement instead of inheriting a whole
    package's surface.
    """

    async def verify(self, handle: str, session_secret: str) -> SessionRecord:
        """The session at ``handle``, if ``session_secret`` matches it."""
        ...

    async def get(self, handle: str) -> SessionRecord:
        """The session at ``handle``, secret unchecked (addressing a peer)."""
        ...

    async def query(
        self, *, scope_contains: str | None = None, capability: str | None = None
    ) -> QueryResult:
        """Sessions matching a directory query (a broadcast's recipients)."""
        ...


class MessengerService:
    """Messenger operations backing the ``messenger_*`` tool family and the
    ``/api/messenger`` REST mirror.

    Args:
        store: the hub's one messenger database.
        directory: the SPEC-402 session directory, for authenticating a
            caller's handle and for resolving a recipient (or a broadcast
            query) to live sessions.
        ref_validator: resolves an envelope's ``memory://`` refs. ``None``
            means this hub cannot check them, and a send carrying refs is
            then **refused** rather than accepted unchecked — fail-closed,
            because an unvalidated ref is exactly the dangling pointer the
            body cap's escape hatch cannot afford.
        publish: the event sink. ``None`` (or left unset) runs a fully
            working messenger that simply publishes nothing, same as
            ``StashService``/``DirectoryService``.
    """

    def __init__(
        self,
        store: MessengerStore,
        directory: SessionLookup,
        *,
        ref_validator: RefValidator | None = None,
        publish: Publisher | None = None,
    ) -> None:
        self._store = store
        self._directory = directory
        self._ref_validator = ref_validator
        #: Public and reassignable, same reason as ``StashService.publish``:
        #: ``palaia_hub.app.create_app`` builds the service before it has an
        #: event bus in hand.
        self.publish = publish

    # -- events ----------------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.publish is not None:
            self.publish(event_type, data)

    def _emit_expired(self, expired: list[EnvelopeMetadata]) -> None:
        """``message.expired``, once per envelope the sweep just deleted."""
        for metadata in expired:
            self._emit("message.expired", metadata.model_dump())

    # -- authorization ---------------------------------------------------

    async def _authenticate(self, handle: str, session_secret: str) -> SessionRecord:
        try:
            return await self._directory.verify(handle, session_secret)
        except DirectoryError as exc:
            # Re-raised as a messenger error so every caller of this module
            # catches exactly one exception family. The directory's own
            # message already names the fault precisely ("no session
            # registered at handle X" / "session secret does not match") —
            # and identically for both, so a wrong secret cannot be told
            # apart from an unknown handle by the error it produces.
            raise SessionAuthError(
                f"{exc} Fix: use the handle and session_secret this session got "
                "from directory_register — the messenger reads only your own inbox."
            ) from exc

    # -- send ------------------------------------------------------------

    async def send(
        self,
        *,
        sender: str,
        session_secret: str,
        message_type: MessageType,
        to: str,
        subject: str,
        body: str = "",
        urgency: Urgency = "normal",
        expects_reply: bool = False,
        refs: list[str] | None = None,
        reply_to: str | None = None,
        ttl_seconds: float | None = None,
        readable_vaults: frozenset[str] | None = None,
    ) -> SendResult:
        """Validate, address and store one envelope (or a broadcast's fan-out).

        Order matters and is deliberate: the caller is authenticated first,
        then the cheap structural checks, then the refs (an index read),
        then the directory resolution, and only then is anything written.
        Nothing lands in an inbox until every check has passed — a partially
        delivered broadcast is not a state this store can reach.
        """
        await self._authenticate(sender, session_secret)
        return await self._send(
            sender=sender,
            message_type=message_type,
            to=to,
            subject=subject,
            body=body,
            urgency=urgency,
            expects_reply=expects_reply,
            refs=refs,
            reply_to=reply_to,
            ttl_seconds=ttl_seconds,
            readable_vaults=readable_vaults,
            fence_reply=True,
        )

    async def send_as_owner(
        self,
        *,
        message_type: MessageType,
        to: str,
        subject: str,
        body: str = "",
        urgency: Urgency = "normal",
        expects_reply: bool = False,
        refs: list[str] | None = None,
        reply_to: str | None = None,
        ttl_seconds: float | None = None,
        readable_vaults: frozenset[str] | None = None,
    ) -> SendResult:
        """Owner control: send as the hub's owner (SPEC-405 deliverable #2,
        MASTERPLAN §5.4 trust rule #7 — "the human can ... join in").

        No SPEC-402 session secret is checked here — there is no session to
        prove one for. This is safe only because it has exactly one caller,
        :mod:`palaia_hub.messenger_api`'s ``POST /api/messenger/send``,
        which sits behind the owner's signed-in session and CSRF token
        (:mod:`palaia_hub.admin_session`): a *stronger* proof of "this really
        is the owner" than a session secret is of "this really is session
        X", not a weaker substitute for it. The sender is always
        :data:`~palaia_hub.messenger.models.OWNER_HANDLE`, and a reply is not
        fenced to a thread the owner already took part in — reading along
        and then answering is exactly trust rule #7's "join in", so the
        fence :meth:`send` applies to an ordinary session does not apply
        here.
        """
        return await self._send(
            sender=OWNER_HANDLE,
            message_type=message_type,
            to=to,
            subject=subject,
            body=body,
            urgency=urgency,
            expects_reply=expects_reply,
            refs=refs,
            reply_to=reply_to,
            ttl_seconds=ttl_seconds,
            readable_vaults=readable_vaults,
            fence_reply=False,
        )

    async def _send(
        self,
        *,
        sender: str,
        message_type: MessageType,
        to: str,
        subject: str,
        body: str,
        urgency: Urgency,
        expects_reply: bool,
        refs: list[str] | None,
        reply_to: str | None,
        ttl_seconds: float | None,
        readable_vaults: frozenset[str] | None,
        fence_reply: bool,
    ) -> SendResult:
        """The validate-address-store pipeline shared by :meth:`send` (an
        authenticated session, fenced to threads it took part in) and
        :meth:`send_as_owner` (already-authenticated by the dashboard's own
        gate, never fenced) — one implementation of "what a send actually
        does", not two copies that could drift.
        """
        clean_refs = check_refs(refs)
        self._check_refs_resolve(clean_refs, readable_vaults)
        parent = await self._reply_target(reply_to)
        if fence_reply and parent is not None and sender not in (
            parent.envelope.from_,
            parent.recipient,
        ):
            raise NotYourEnvelopeError(
                f"envelope {reply_to!r} is not yours to reply to — you are neither "
                "its sender nor its recipient. Fix: reply only to envelopes "
                "messenger_check handed you."
            )
        if parent is not None and message_type == "broadcast":
            raise InvalidEnvelopeError(
                "a broadcast cannot be a reply. Fix: reply to the one envelope you "
                "are answering (its type may be anything else), or send a fresh "
                "broadcast with reply_to unset."
            )
        if message_type == "broadcast":
            recipients = await self._broadcast_recipients(sender, to)
            addressed_to = to.strip()
            broadcast: str | None = addressed_to
        else:
            recipient = await self._directed_recipient(to)
            recipients = [recipient]
            addressed_to = recipient
            broadcast = None

        items, expired = await asyncio.to_thread(
            self._store.create,
            type=message_type,
            sender=sender,
            addressed_to=addressed_to,
            recipients=recipients,
            subject=subject,
            urgency=urgency,
            expects_reply=expects_reply,
            body=body,
            refs=clean_refs,
            reply_to=reply_to,
            ttl_seconds=ttl_seconds,
        )
        self._emit_expired(expired)
        for item in items:
            self._emit("message.sent", EnvelopeMetadata.of(item).model_dump())
        return SendResult(
            envelopes=[item.envelope for item in items],
            recipients=[item.recipient for item in items],
            broadcast_query=broadcast,
        )

    def _check_refs_resolve(
        self, refs: list[str], readable_vaults: frozenset[str] | None
    ) -> None:
        if not refs:
            return
        if self._ref_validator is None:
            raise UnresolvableRefError(
                "this hub cannot validate memory:// references (no vault index is "
                f"wired into the messenger), so it refuses to carry {refs}. Fix: "
                "send the message without refs, or ask the operator to run the hub "
                "with its vaults open."
            )
        missing = self._ref_validator.unresolvable(refs, readable_vaults=readable_vaults)
        if missing:
            raise UnresolvableRefError(
                f"these refs resolve to nothing you can read: {missing}. Fix: write "
                "the note first (the memory tools' write), then reference its real "
                "permalink — a recipient cannot follow a reference that points "
                "nowhere, which is the whole reason refs exists."
            )

    async def _reply_target(self, reply_to: str | None) -> InboxItem | None:
        """The envelope ``reply_to`` names, or ``None`` — no participant
        fence here (that is :meth:`_send`'s job, via ``fence_reply``): an
        ordinary session's reply may only answer a thread it took part in,
        but the owner's :meth:`send_as_owner` may reply to anything (trust
        rule #7's "join in"), and this helper is what both share.
        """
        if reply_to is None:
            return None
        item, expired = await asyncio.to_thread(self._store.item, reply_to)
        self._emit_expired(expired)
        if item is None:
            raise EnvelopeNotFoundError(
                f"reply_to names no envelope ({reply_to!r}). Fix: reply to an id "
                "messenger_check gave you — an envelope past its expires_at is gone."
            )
        return item

    async def _directed_recipient(self, to: str) -> str:
        """The recipient handle, refusing an unknown or stale session in
        plain language (SPEC-403 deliverable #3)."""
        handle = to.strip()
        if not handle:
            raise InvalidEnvelopeError(
                "to is empty. Fix: address this message to a handle from "
                "directory_list/directory_query, or set type='broadcast' and put a "
                "directory query in to."
            )
        try:
            session = await self._directory.get(handle)
        except DirectoryError as exc:
            raise UnknownRecipientError(
                f"no session is registered at handle {handle!r}, so there is no "
                "inbox to deliver to. Fix: run directory_list or directory_query to "
                f"find a live handle ({exc})."
            ) from exc
        if session.status == "stale":
            raise StaleRecipientError(
                f"session {handle!r} is stale — it has missed its heartbeat, so it "
                "may already be gone and would never read this. Fix: pick a live "
                "session with directory_query, or broadcast to the scope instead of "
                "one handle."
            )
        return session.handle

    async def _broadcast_recipients(self, sender: str, to: str) -> list[str]:
        """Resolve a broadcast's directory query, capped hard at
        :data:`~palaia_hub.messenger.models.MAX_BROADCAST_RECIPIENTS`.

        Over the cap is a **loud error**, never a silent truncation: a
        broadcast that reached 20 of 40 sessions and reported success is
        indistinguishable from one that reached everybody, and the sender
        would never learn which half missed it.
        """
        query = to.strip()
        if not query:
            raise InvalidEnvelopeError(
                "a broadcast needs a directory query in to. Fix: '*' for every live "
                "session, 'capability:review' for a capability tag, or any substring "
                "of the scope you mean (e.g. 'billing service')."
            )
        scope_contains, capability = broadcast_query(query)
        result = await self._directory.query(
            scope_contains=scope_contains, capability=capability
        )
        recipients = [
            session.handle
            for session in result.sessions
            if session.handle != sender and session.status != "stale"
        ]
        if not recipients:
            raise BroadcastError(
                f"broadcast query {to!r} matched no live session other than your "
                "own. Fix: widen the query (directory_query with the same value "
                "shows you exactly who it would reach), or address one handle "
                "directly."
            )
        if len(recipients) > MAX_BROADCAST_RECIPIENTS:
            raise BroadcastError(
                f"broadcast query {to!r} matched {len(recipients)} live sessions; the "
                f"hard cap is {MAX_BROADCAST_RECIPIENTS}. Nothing was sent — a "
                "broadcast that silently reached half its audience is worse than "
                "none. Fix: narrow the query (a scope substring or "
                "'capability:<tag>'), or write it to memory once and let the others "
                "recall it."
            )
        return recipients

    # -- read ------------------------------------------------------------

    async def check(self, handle: str, session_secret: str) -> CheckResult:
        """Every new envelope for ``handle``, marked delivered.

        Fires ``message.received`` per envelope — metadata only, which is
        the SPEC's contract test: the body reaches the recipient through
        this call's *result*, and never travels the bus.
        """
        await self._authenticate(handle, session_secret)
        items, expired = await asyncio.to_thread(self._store.check, handle)
        self._emit_expired(expired)
        for item in items:
            self._emit("message.received", EnvelopeMetadata.of(item).model_dump())
        return CheckResult(handle=handle, envelopes=[item.envelope for item in items])

    async def ack(self, handle: str, session_secret: str, envelope_id: str) -> AckResult:
        """Close one envelope in the caller's own inbox."""
        await self._authenticate(handle, session_secret)
        item, expired = await asyncio.to_thread(self._store.ack, envelope_id, handle)
        self._emit_expired(expired)
        return AckResult(id=item.envelope.id, acked=True, state=item.state)

    async def thread(
        self, handle: str, session_secret: str, envelope_id: str
    ) -> ThreadResult:
        """One envelope's reply chain, narrowed to the caller's own copies.

        The narrowing is the fence: a thread can contain envelopes addressed
        to third parties (a handoff answered by somebody else), and this
        caller has no claim on those bodies. They are filtered out rather
        than the whole call being refused, so a legitimate participant still
        sees their own half of the conversation.
        """
        await self._authenticate(handle, session_secret)
        items, expired = await asyncio.to_thread(self._store.thread, envelope_id)
        self._emit_expired(expired)
        mine = [
            item for item in items if handle in (item.envelope.from_, item.recipient)
        ]
        if not mine:
            raise NotYourEnvelopeError(
                f"envelope {envelope_id!r} is not part of any thread you took part "
                "in. Fix: pass an id from your own messenger_check result."
            )
        return ThreadResult(
            root_id=mine[0].envelope.id, envelopes=[item.envelope for item in mine]
        )

    # -- REST mirror (the owner's admin surface) --------------------------

    async def outbox(self, handle: str) -> FlowsResult:
        """One sender's outbox (SPEC-403 deliverable #2's "sender outbox
        view"), as metadata: what this handle sent, and how far each copy
        got — ``pending`` (nobody has checked yet), ``delivered``, ``acked``.

        Read-side only, and bodies withheld like every other listing here.
        A broadcast shows one row per recipient, which is the whole point of
        an outbox view: "who actually got this" is a question a fan-out
        raises and a single ``SendResult`` cannot answer later.
        """
        items, expired = await asyncio.to_thread(self._store.outbox, handle)
        self._emit_expired(expired)
        return FlowsResult(flows=[EnvelopeMetadata.of(item) for item in items])

    async def flows(
        self,
        *,
        handle: str | None = None,
        message_type: MessageType | None = None,
        state: DeliveryState | None = None,
        limit: int = DEFAULT_FLOW_LIMIT,
    ) -> FlowsResult:
        """Recent message flows as metadata — SPEC-403 deliverable #6, the
        feed SPEC-405's observability screen reads. No bodies."""
        items, expired = await asyncio.to_thread(
            self._store.flows,
            handle=handle,
            message_type=message_type,
            state=state,
            limit=limit,
        )
        self._emit_expired(expired)
        return FlowsResult(flows=[EnvelopeMetadata.of(item) for item in items])

    async def thread_metadata(self, envelope_id: str) -> ThreadMetadataResult:
        """One thread as metadata — no bodies, no session secret needed
        (this surface is already behind the admin session gate)."""
        items, expired = await asyncio.to_thread(self._store.thread, envelope_id)
        self._emit_expired(expired)
        return ThreadMetadataResult(
            root_id=items[0].envelope.id if items else envelope_id,
            flows=[EnvelopeMetadata.of(item) for item in items],
        )

    async def envelope_detail(self, envelope_id: str) -> EnvelopeDetailResult:
        """One envelope **with** its body — the owner's read (deliverable
        #6: "bodies only for the owner via the admin surface")."""
        item, expired = await asyncio.to_thread(self._store.item, envelope_id)
        self._emit_expired(expired)
        if item is None:
            raise EnvelopeNotFoundError(
                f"no envelope {envelope_id!r} (never sent, or expired away)."
            )
        return EnvelopeDetailResult(item=item)

    async def end_conversation(self, envelope_id: str) -> EndConversationResult:
        """Owner control: expire a thread's undelivered envelopes (SPEC-405
        deliverable #2, MASTERPLAN §5.4 trust rule #7 — "shut a conversation
        down"). See :meth:`~palaia_hub.messenger.store.MessengerStore.
        expire_thread` for exactly what "undelivered" excludes. Fires
        ``message.expired`` for every envelope this call itself expired, and
        for whatever the routine TTL sweep found on the way in — both are
        the same event, because both mean the same thing to whoever would
        have received them: this envelope will not be delivered.
        """
        root_id, thread_expired, swept = await asyncio.to_thread(
            self._store.expire_thread, envelope_id
        )
        self._emit_expired(swept)
        self._emit_expired(thread_expired)
        return EndConversationResult(root_id=root_id, expired=thread_expired)

    async def sweep(self) -> list[EnvelopeMetadata]:
        """Run the TTL sweep alone and fire ``message.expired`` for each.

        The store already sweeps on every call, so nothing depends on this
        being invoked — it exists so a hub (or a test) can make expiry
        happen at a moment of its choosing instead of at whatever moment the
        next reader happens to arrive.
        """
        expired = await asyncio.to_thread(self._store.sweep)
        self._emit_expired(expired)
        return expired


def envelope_summary(envelope: Envelope) -> str:
    """One compact line for an envelope: type, urgency, sender, subject, refs.

    The messenger's text rendering is compact **by design** (SPEC-403
    deliverable #3) — a session polling its inbox should pay for a subject
    line, not for every body it has not decided to read yet. Shared by the
    tool family and the tests so the rule has one implementation.
    """
    parts = [f"[{envelope.type}/{envelope.urgency} from {envelope.from_}] {envelope.subject}"]
    if envelope.expects_reply:
        parts.append("(reply expected)")
    if envelope.refs:
        parts.append(f"refs: {', '.join(envelope.refs)}")
    return " ".join(parts)


__all__ = ["MessengerService", "Publisher", "SessionLookup", "envelope_summary"]
