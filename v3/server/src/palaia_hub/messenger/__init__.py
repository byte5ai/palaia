"""The messenger: typed, token-disciplined messages between sessions
(SPEC-403, MASTERPLAN §5.4's second half).

Four things stopped agents messaging each other, and the masterplan names
all four. SPEC-402's directory fixed *discovery* and *addressing*; this
package is the other two:

- **Protocol, not chat.** A message is a
  :class:`~palaia_hub.messenger.models.Envelope` — a fixed dict with a
  type, a subject, an urgency, an expects-reply flag, a short body and
  ``memory://`` references into the vault. Long content is written to
  memory once and pointed at, never re-serialized into every message. The
  4096-byte body cap is that rule as a mechanism, not as advice.
- **Delivery.** Pull, over MCP tools (``messenger_send``/``check``/``ack``/
  ``thread``): MCP 2026-07-28 removed server-initiated requests, so polling
  carries the async semantics. Push adapters are SPEC-404's.

Public surface:

- :class:`~palaia_hub.messenger.store.MessengerStore` — the SQLite engine:
  per-recipient inbox, delivery state, TTL sweep, thread walk, outbox.
- :class:`~palaia_hub.messenger.service.MessengerService` — the async
  facade the gateway tools and the REST mirror both call. Owns the
  session-secret fence and the ``message.*`` events.
- :mod:`palaia_hub.messenger.models` — the envelope and the result shapes.
- :class:`~palaia_hub.messenger.refs.VaultRefValidator` — the one piece
  that knows the recall/index stack, so the mailbox itself does not.
"""

from __future__ import annotations

from .models import (
    DEFAULT_TTL_SECONDS,
    MAX_BODY_BYTES,
    MAX_BROADCAST_RECIPIENTS,
    MAX_SUBJECT_CHARS,
    MAX_TTL_SECONDS,
    AckResult,
    BodyTooLargeError,
    BroadcastError,
    CheckResult,
    DeliveryState,
    Envelope,
    EnvelopeDetailResult,
    EnvelopeMetadata,
    EnvelopeNotFoundError,
    FlowsResult,
    InboxItem,
    InvalidEnvelopeError,
    MessageType,
    MessengerError,
    NotYourEnvelopeError,
    RefValidator,
    SendResult,
    SessionAuthError,
    StaleRecipientError,
    SubjectTooLongError,
    ThreadMetadataResult,
    ThreadResult,
    UnknownRecipientError,
    UnresolvableRefError,
    Urgency,
)
from .refs import VaultRefValidator, build_vault_ref_validator
from .service import MessengerService, Publisher, SessionLookup, envelope_summary
from .store import DEFAULT_FLOW_LIMIT, MessengerStore

__all__ = [
    "DEFAULT_FLOW_LIMIT",
    "DEFAULT_TTL_SECONDS",
    "MAX_BODY_BYTES",
    "MAX_BROADCAST_RECIPIENTS",
    "MAX_SUBJECT_CHARS",
    "MAX_TTL_SECONDS",
    "AckResult",
    "BodyTooLargeError",
    "BroadcastError",
    "CheckResult",
    "DeliveryState",
    "Envelope",
    "EnvelopeDetailResult",
    "EnvelopeMetadata",
    "EnvelopeNotFoundError",
    "FlowsResult",
    "InboxItem",
    "InvalidEnvelopeError",
    "MessageType",
    "MessengerError",
    "MessengerService",
    "MessengerStore",
    "NotYourEnvelopeError",
    "Publisher",
    "RefValidator",
    "SendResult",
    "SessionAuthError",
    "SessionLookup",
    "StaleRecipientError",
    "SubjectTooLongError",
    "ThreadMetadataResult",
    "ThreadResult",
    "UnknownRecipientError",
    "UnresolvableRefError",
    "Urgency",
    "VaultRefValidator",
    "build_vault_ref_validator",
    "envelope_summary",
]
