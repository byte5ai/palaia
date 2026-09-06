"""The messenger envelope and its result shapes (SPEC-403 deliverable #1).

**The envelope is the protocol.** Its shape is fixed by the SPEC and
implemented verbatim here — ``{id, type, from, to, subject, urgency,
expects_reply, body, refs, reply_to, created_at, expires_at}``. Nothing may
be added to it casually: two sessions on different providers agree on this
dict and nothing else, so a field that appears on one hub and not another
is a protocol fork. Everything the *hub* knows about an envelope but the
protocol does not — which inbox holds this copy, whether it has been
delivered or acked — lives on :class:`InboxItem` around the envelope, not
inside it.

``from`` is a Python keyword, so the field is spelled ``from_``, validates
from either name (``validation_alias``) and — because ``serialize_by_alias``
is set — always *serializes* as ``from`` (``serialization_alias``). Split
across those two settings rather than one plain ``alias=`` on purpose:
``alias`` also renames the keyword in pydantic's synthesized ``__init__``,
which would make every construction in this package read
``Envelope(**{"from": ...})``. The wire shape is what the SPEC fixed; the
attribute name is an implementation detail of this file.

**The body cap is the token-discipline rule as a mechanism** (MASTERPLAN
§5.4): :data:`MAX_BODY_BYTES` is a hard cap measured in UTF-8 bytes, and
:func:`check_body` refuses an over-long body with an error that names the
fix — write it to memory once and point at it with ``refs`` — rather than
truncating, which would silently lose the half nobody re-read.

**Never the body on the bus.** :class:`EnvelopeMetadata` is the envelope
with its body withheld and the hub's own delivery state added. It is the
one shape the event bus (``message.sent``/``message.received``/
``message.expired``) and the ``/api/messenger`` observability mirror both
use, so "the body never leaves the hub except to its recipient" is one
class's invariant instead of a rule restated at every call site.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

#: The envelope's ``type`` vocabulary, verbatim from SPEC-403 deliverable #1
#: / MASTERPLAN §5.4. Typed messages, not chat: a recipient can route on
#: this without reading a word of the body.
MessageType = Literal["request", "inform", "question", "handoff", "broadcast"]

#: The envelope's ``urgency`` vocabulary.
Urgency = Literal["low", "normal", "high"]

#: Where one envelope copy stands in its recipient's inbox. ``pending`` — it
#: has been sent but the recipient has not run ``messenger_check`` yet;
#: ``delivered`` — a check handed it over (and fired ``message.received``);
#: ``acked`` — the recipient closed it with ``messenger_ack``. Never an
#: input a caller sets directly.
DeliveryState = Literal["pending", "delivered", "acked"]

#: Hard cap on ``subject``, in characters (SPEC-403 deliverable #1).
MAX_SUBJECT_CHARS = 200

#: Hard cap on ``body``, in UTF-8 **bytes** — not characters (SPEC-403
#: deliverable #1). Bytes, because that is what a transport and a token
#: budget actually pay for, and because a cap in characters would let a
#: body of emoji cost four times a body of ASCII.
MAX_BODY_BYTES = 4096

#: Default time-to-live for an envelope: 24 hours (SPEC-403 deliverable #2).
DEFAULT_TTL_SECONDS = 86_400.0

#: The longest TTL a sender may ask for: 7 days (SPEC-403 deliverable #2).
#: An envelope is a message, not a record — anything that should outlive a
#: week belongs in the vault, which is what ``refs`` is for.
MAX_TTL_SECONDS = 604_800.0

#: The most recipients one ``broadcast`` may fan out to (SPEC-403
#: deliverable #2, hard cap). A query resolving to more than this is
#: refused with the count, not silently truncated: a partial broadcast that
#: looks like a whole one is worse than no broadcast.
MAX_BROADCAST_RECIPIENTS = 20

#: The scheme every ``refs`` entry must carry. Required explicitly (the
#: resolver itself would accept a bare permalink) so an envelope's ``refs``
#: is unambiguously a list of addresses and never a list of loose words.
MEMORY_SCHEME = "memory://"

#: ``to`` prefix selecting a capability-tag broadcast rather than the
#: default scope-substring one — see :func:`broadcast_query`.
CAPABILITY_QUERY_PREFIX = "capability:"

#: ``to`` value meaning "every live session in the directory".
EVERYONE_QUERY = "*"

#: The ``from`` every owner-sent envelope carries (SPEC-405 deliverable #2:
#: "send as owner"). Never a SPEC-402 directory handle — the owner has no
#: session to register, and never needs one: the dashboard's own
#: ``/api/messenger/send`` route is already behind the owner's signed-in
#: session and CSRF token (:mod:`palaia_hub.admin_session`), which is what
#: :meth:`~palaia_hub.messenger.service.MessengerService.send_as_owner`
#: trusts instead of a session secret. A real directory handle can never
#: collide with this value (handles are random
#: :data:`~palaia_hub.directory.store.HANDLE_CHARS`-character tokens, never
#: a plain word), so a recipient can tell "the owner" apart from any agent
#: session on sight.
OWNER_HANDLE = "owner"


class Envelope(BaseModel):
    """One message between two sessions — the fixed protocol shape.

    Every field is server-minted or sender-supplied-and-validated; none is
    optional at rest (``reply_to`` is nullable, not absent). See the module
    docstring for why ``from_`` is spelled with a trailing underscore.
    """

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, serialize_by_alias=True
    )

    #: Server-minted. Never supplied by a sender — an envelope id is the
    #: only handle a reply, an ack or a thread walk has, so a caller able to
    #: choose one could overwrite or hijack somebody else's message.
    id: str
    type: MessageType
    #: The sender's directory handle (SPEC-402), proven by their session
    #: secret at send time — see :mod:`palaia_hub.messenger.service`.
    from_: str = Field(
        validation_alias=AliasChoices("from", "from_"), serialization_alias="from"
    )
    #: The recipient handle as *addressed*: a directory handle for every
    #: type but ``broadcast``, and the directory query itself for a
    #: broadcast (so a broadcast copy still says what net it was cast
    #: with). Which inbox this copy actually landed in is
    #: :attr:`InboxItem.recipient`, not this field.
    to: str
    subject: str
    urgency: Urgency
    expects_reply: bool
    body: str
    #: ``memory://`` references, each validated at send time to resolve in
    #: a vault the sender can read (SPEC-403 deliverable #1). This is where
    #: long content goes — once, in the vault — instead of into the body.
    refs: list[str]
    #: The envelope this one answers, or ``None``. The only thread link
    #: there is: :meth:`palaia_hub.messenger.store.MessengerStore.thread`
    #: walks it up to the root and back down again.
    reply_to: str | None
    created_at: float
    expires_at: float

    @property
    def body_bytes(self) -> int:
        return len(self.body.encode("utf-8"))


class InboxItem(BaseModel):
    """One envelope copy in one inbox: the protocol shape plus the hub's own
    delivery bookkeeping.

    Kept deliberately *outside* :class:`Envelope` — see the module
    docstring. A broadcast fans out to one of these per recipient, each
    wrapping its own separately-minted envelope.
    """

    model_config = ConfigDict(extra="forbid")

    envelope: Envelope
    #: The handle whose inbox holds this copy. Equal to ``envelope.to`` for
    #: everything but a broadcast, where ``to`` is the query instead.
    recipient: str
    state: DeliveryState
    delivered_at: float | None
    acked_at: float | None


class EnvelopeMetadata(BaseModel):
    """An envelope with its **body withheld**, plus delivery state.

    The single shape used by every surface that must not carry a body: the
    three ``message.*`` events (SPEC-403 deliverable #5 — "never the body")
    and the ``/api/messenger`` observability mirror (deliverable #6 —
    "bodies only for the owner via the admin surface"). ``body_bytes`` is
    the honest substitute: how much there is to read, without reading it.

    There is no ``body`` field here, and adding one would be a security
    regression, not a feature — the contract test in
    ``tests/messenger/test_service.py`` asserts as much against the live
    event bus.
    """

    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, serialize_by_alias=True
    )

    id: str
    type: MessageType
    from_: str = Field(
        validation_alias=AliasChoices("from", "from_"), serialization_alias="from"
    )
    to: str
    recipient: str
    subject: str
    urgency: Urgency
    expects_reply: bool
    refs: list[str]
    reply_to: str | None
    created_at: float
    expires_at: float
    state: DeliveryState
    body_bytes: int

    @classmethod
    def of(cls, item: InboxItem) -> EnvelopeMetadata:
        envelope = item.envelope
        return cls(
            id=envelope.id,
            type=envelope.type,
            from_=envelope.from_,
            to=envelope.to,
            recipient=item.recipient,
            subject=envelope.subject,
            urgency=envelope.urgency,
            expects_reply=envelope.expects_reply,
            refs=list(envelope.refs),
            reply_to=envelope.reply_to,
            created_at=envelope.created_at,
            expires_at=envelope.expires_at,
            state=item.state,
            body_bytes=envelope.body_bytes,
        )


# -- results ------------------------------------------------------------------


class SendResult(BaseModel):
    """``messenger_send``'s result: every envelope actually minted.

    One element for a directed message; one per resolved recipient for a
    broadcast (each with its own id — "fans out as individual envelopes",
    SPEC-403 deliverable #2).
    """

    model_config = ConfigDict(extra="forbid")

    envelopes: list[Envelope]
    recipients: list[str]
    #: The directory query a broadcast was resolved from, else ``None``.
    broadcast_query: str | None = None


class CheckResult(BaseModel):
    """``messenger_check``'s result: every envelope in the caller's own inbox
    that is not acked yet — the new ones now marked delivered, plus the ones
    an earlier check already delivered (issue #340)."""

    model_config = ConfigDict(extra="forbid")

    handle: str
    envelopes: list[Envelope]
    #: Ids in ``envelopes`` that an earlier ``check`` already returned and
    #: nobody acked since. Empty on a first read.
    redelivered: list[str] = Field(default_factory=list)


class AckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    acked: bool
    state: DeliveryState


class ThreadResult(BaseModel):
    """``messenger_thread``'s result: one envelope's whole reply chain,
    oldest first, narrowed to the copies the caller took part in."""

    model_config = ConfigDict(extra="forbid")

    root_id: str
    envelopes: list[Envelope]


class FlowsResult(BaseModel):
    """``GET /api/messenger`` — message flows as **metadata only**."""

    model_config = ConfigDict(extra="forbid")

    flows: list[EnvelopeMetadata]


class ThreadMetadataResult(BaseModel):
    """``GET /api/messenger/threads/{id}`` — a thread as metadata only."""

    model_config = ConfigDict(extra="forbid")

    root_id: str
    flows: list[EnvelopeMetadata]


class EndConversationResult(BaseModel):
    """Owner control: "end a conversation" (SPEC-405 deliverable #2,
    MASTERPLAN §5.4 trust rule #7 — "shut a conversation down").

    ``expired`` is only the envelopes this call itself expired — the
    thread's still-``pending`` (undelivered) copies. Delivered/acked copies
    are left alone: the SPEC's own words are "expires the thread's
    undelivered envelopes", not "deletes the conversation's history", and a
    recipient who already has a copy locally is not un-sent to by this
    call. Deliberately not exposed as an MCP tool: the SPEC-304 rule this
    SPEC inherits keeps destructive owner controls dashboard-only, and this
    is one — see :mod:`palaia_hub.messenger_api`.
    """

    model_config = ConfigDict(extra="forbid")

    root_id: str
    expired: list[EnvelopeMetadata]


class EnvelopeDetailResult(BaseModel):
    """``GET /api/messenger/envelopes/{id}`` — the owner's body-bearing read
    (SPEC-403 deliverable #6: "bodies only for the owner via the admin
    surface", which is exactly what ``/api/*`` behind
    :mod:`palaia_hub.admin_session` is)."""

    model_config = ConfigDict(extra="forbid")

    item: InboxItem


# -- errors -------------------------------------------------------------------


class MessengerError(Exception):
    """Raised for a bad messenger call.

    Turned into a ``ToolResult(is_error=True, ...)`` by the gateway layer
    and into a 400/404 by the REST mirror — never an uncaught exception
    (same convention as ``StashError``/``DirectoryError``). Every subclass
    below carries a message that names the fix, not just the fault.
    """


class BodyTooLargeError(MessengerError):
    """The body exceeded :data:`MAX_BODY_BYTES`. The SPEC's "loud error
    naming the fix: write it to memory and reference it"."""


class SubjectTooLongError(MessengerError):
    """The subject exceeded :data:`MAX_SUBJECT_CHARS`."""


class InvalidEnvelopeError(MessengerError):
    """The envelope is structurally wrong before anything is looked up: an
    empty subject, an empty ``to``, a ``refs`` entry that is not a
    ``memory://`` reference, a TTL over :data:`MAX_TTL_SECONDS`."""


class UnresolvableRefError(MessengerError):
    """A ``refs`` entry resolves in no vault the sender can read."""


class UnknownRecipientError(MessengerError):
    """No session is registered at the addressed handle (SPEC-403
    deliverable #3: "refuses a stale/unknown recipient with a plain-language
    error")."""


class StaleRecipientError(MessengerError):
    """The addressed session is past its heartbeat TTL — it may already be
    gone, so the message would rot in an inbox nobody reads."""


class BroadcastError(MessengerError):
    """A broadcast's directory query resolved to nothing, or to more than
    :data:`MAX_BROADCAST_RECIPIENTS` sessions."""


class EnvelopeNotFoundError(MessengerError):
    """No envelope with that id — never sent, or already expired away."""


class SessionAuthError(MessengerError):
    """The caller's handle and session secret do not match a registered
    session — an unknown handle, a wrong secret, or a handle that has aged
    out of the directory.

    The first half of SPEC-403 deliverable #4: *a scope alone must not read
    another session's inbox*. A token's scopes say what a client may do;
    only this credential (the SPEC-402 session secret, reused — never a
    second one) says which session it is.
    """


class NotYourEnvelopeError(MessengerError):
    """The caller is authenticated, but the envelope is not theirs — they
    are neither its sender nor its recipient. The other half of the inbox
    fence: knowing an envelope id is not a claim on it."""


# -- pure validation ----------------------------------------------------------


def check_subject(subject: str) -> str:
    """The subject, stripped — or an error naming the cap it broke."""
    text = subject.strip()
    if not text:
        raise InvalidEnvelopeError(
            "subject is empty. Fix: give this message a one-line subject — it is "
            "what a recipient routes on before reading anything else."
        )
    if len(text) > MAX_SUBJECT_CHARS:
        raise SubjectTooLongError(
            f"subject is {len(text)} characters; the limit is {MAX_SUBJECT_CHARS}. "
            "Fix: shorten it to one line — the detail belongs in the body, and "
            "anything long belongs in memory with a memory:// reference in refs."
        )
    return text


def check_body(body: str) -> str:
    """The body — or the SPEC's loud, fix-naming error.

    The cap is measured in UTF-8 bytes (:data:`MAX_BODY_BYTES`), and the
    message says both numbers so a caller does not have to guess how far
    over it is.
    """
    size = len(body.encode("utf-8"))
    if size > MAX_BODY_BYTES:
        raise BodyTooLargeError(
            f"body is {size} UTF-8 bytes; the hard limit is {MAX_BODY_BYTES}. "
            "Fix: write it to memory and reference it — put the long content in "
            "a note with the memory tools' write, then pass that note's "
            "memory:// permalink in refs and keep the body to a short summary. "
            "Messages point at knowledge; they do not carry it."
        )
    return body


def check_refs(refs: list[str] | None) -> list[str]:
    """The refs list, whitespace-trimmed, every entry scheme-qualified."""
    cleaned: list[str] = []
    for ref in refs or []:
        text = ref.strip()
        if not text:
            continue
        if not text.lower().startswith(MEMORY_SCHEME):
            raise InvalidEnvelopeError(
                f"refs entry {ref!r} is not a memory:// reference. Fix: write it "
                f"as {MEMORY_SCHEME}<permalink> (e.g. "
                f"{MEMORY_SCHEME}projects/api-gateway) — refs addresses notes in "
                "a vault, it is not a free-text field."
            )
        cleaned.append(text)
    return cleaned


def check_ttl(ttl_seconds: float | None) -> float:
    """The TTL to apply: the default when unset, or an error over the cap."""
    if ttl_seconds is None:
        return DEFAULT_TTL_SECONDS
    if ttl_seconds <= 0:
        raise InvalidEnvelopeError(
            f"ttl_seconds must be positive (got {ttl_seconds}). Fix: leave it "
            f"unset for the {DEFAULT_TTL_SECONDS / 3600:.0f}h default."
        )
    if ttl_seconds > MAX_TTL_SECONDS:
        raise InvalidEnvelopeError(
            f"ttl_seconds is {ttl_seconds:.0f}; the maximum is "
            f"{MAX_TTL_SECONDS:.0f} (7 days). Fix: a message that must outlive a "
            "week is not a message — write it to memory and reference it."
        )
    return float(ttl_seconds)


def broadcast_query(to: str) -> tuple[str | None, str | None]:
    """A broadcast's ``to`` as ``(scope_contains, capability)``.

    The grammar is deliberately tiny, and documented on the tool itself:

    * ``"*"`` — every live session (both filters ``None``).
    * ``"capability:<tag>"`` — sessions carrying that capability tag.
    * anything else — a case-insensitive substring of a session's
      self-reported ``scope`` ("who is working on repo X", MASTERPLAN §5.4).

    Nothing richer, on purpose: a query language here would be a second
    addressing system next to the directory's own
    (:meth:`palaia_hub.directory.service.DirectoryService.query`), and the
    directory is the one place discovery is supposed to live.
    """
    text = to.strip()
    if text == EVERYONE_QUERY:
        return None, None
    if text.lower().startswith(CAPABILITY_QUERY_PREFIX):
        tag = text[len(CAPABILITY_QUERY_PREFIX) :].strip()
        if not tag:
            raise InvalidEnvelopeError(
                f"broadcast query {to!r} names no capability. Fix: write "
                f"'{CAPABILITY_QUERY_PREFIX}review' to reach every session "
                "tagged 'review'."
            )
        return None, tag
    return text, None


class RefValidator(Protocol):
    """What the messenger needs of a vault index: "do these refs resolve?".

    A protocol rather than a concrete dependency so
    :mod:`palaia_hub.messenger.service` never imports the recall/index
    stack — the real implementation
    (:class:`palaia_hub.messenger.refs.VaultRefValidator`) does, and a test
    can pass a two-line fake.
    """

    def unresolvable(
        self, refs: list[str], *, readable_vaults: frozenset[str] | None = None
    ) -> list[str]:
        """The subset of ``refs`` that resolves in none of the vaults named
        by ``readable_vaults`` (``None`` — every vault this validator
        knows)."""
        ...


__all__ = [
    "CAPABILITY_QUERY_PREFIX",
    "DEFAULT_TTL_SECONDS",
    "EVERYONE_QUERY",
    "MAX_BODY_BYTES",
    "MAX_BROADCAST_RECIPIENTS",
    "MAX_SUBJECT_CHARS",
    "MAX_TTL_SECONDS",
    "MEMORY_SCHEME",
    "OWNER_HANDLE",
    "AckResult",
    "BodyTooLargeError",
    "BroadcastError",
    "CheckResult",
    "DeliveryState",
    "EndConversationResult",
    "Envelope",
    "EnvelopeDetailResult",
    "EnvelopeMetadata",
    "EnvelopeNotFoundError",
    "FlowsResult",
    "InboxItem",
    "InvalidEnvelopeError",
    "MessageType",
    "MessengerError",
    "NotYourEnvelopeError",
    "RefValidator",
    "SendResult",
    "SessionAuthError",
    "StaleRecipientError",
    "SubjectTooLongError",
    "ThreadMetadataResult",
    "ThreadResult",
    "UnknownRecipientError",
    "UnresolvableRefError",
    "Urgency",
    "broadcast_query",
    "check_body",
    "check_refs",
    "check_subject",
    "check_ttl",
]
