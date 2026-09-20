"""Turning one raw Telegram ``Update`` into the hub's own record (issue #411).

One function, and it is deliberately **total**: every update shape either
becomes an :class:`~palaia_hub.telegram.models.InboundMessage` or becomes
``None``, and nothing raises. That matters more than it looks — the poller
advances its offset from ``update_id`` whether or not the update was
understood, so an update type this connector has never heard of must not be
able to wedge the poll loop by raising on the way past. A ``None`` is
normal, not an error.

Telegram's ``Update`` carries exactly one payload field. Four of them are
messages in the sense this connector means (``message``,
``edited_message``, ``channel_post``, ``edited_channel_post``) and are what
:data:`~palaia_hub.telegram.models.ALLOWED_UPDATES` asks for; the rest —
callback queries, inline queries, poll answers, chat-member changes — are
out of scope for the first cut and normalise to ``None``.

**Text and caption are one field here.** Telegram puts a message's words in
``text`` when there is no media and in ``caption`` when there is. A route
that matched on one and not the other would be a trap, so the normalised
record has a single ``text``.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import Attachment, InboundMessage

logger = logging.getLogger("palaia_hub.telegram.updates")

#: Update key → whether that payload is an edit. Order matters only in that
#: the first match wins; Telegram sends exactly one of these per update.
_MESSAGE_KEYS: tuple[tuple[str, bool], ...] = (
    ("message", False),
    ("channel_post", False),
    ("edited_message", True),
    ("edited_channel_post", True),
)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    """``value`` when it is a JSON object, else ``{}``.

    Telegram omits optional sub-objects entirely rather than nulling them
    (``from`` is absent on a channel post, not ``None``), so "missing" and
    "empty" are the same thing to every caller here."""
    return value if isinstance(value, dict) else {}


def _full_name(user: dict[str, Any]) -> str | None:
    parts = [_str_or_none(user.get("first_name")), _str_or_none(user.get("last_name"))]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _attachments(message: dict[str, Any]) -> list[Attachment]:
    """Media *references* on this message — never bytes (see
    :class:`~palaia_hub.telegram.models.Attachment`).

    ``photo`` is a list of the same image at several sizes; only the largest
    is recorded, because "which resolution" is a download-time decision and
    four entries for one photo would make every routed message look like an
    album.
    """
    found: list[Attachment] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = max(
            (p for p in photos if isinstance(p, dict)),
            key=lambda p: p.get("file_size") or 0,
            default=None,
        )
        if largest is not None:
            found.append(_attachment("photo", largest))
    for kind in ("document", "audio", "video", "voice", "animation", "sticker"):
        payload = message.get(kind)
        if isinstance(payload, dict):
            found.append(_attachment(kind, payload))
    return [a for a in found if a is not None]


def _attachment(kind: str, payload: dict[str, Any]) -> Attachment:
    return Attachment(
        kind=kind,  # type: ignore[arg-type]
        file_id=str(payload.get("file_id") or ""),
        file_unique_id=str(payload.get("file_unique_id") or ""),
        file_name=_str_or_none(payload.get("file_name")),
        mime_type=_str_or_none(payload.get("mime_type")),
        file_size=_int_or_none(payload.get("file_size")),
    )


def normalise_update(bot: str, update: dict[str, Any]) -> InboundMessage | None:
    """The hub's record for ``update``, or ``None`` if it is not a message.

    Args:
        bot: the hub-side bot key that received this update — the connector's
            own name for the bot, not anything Telegram knows.
        update: one raw ``Update`` object, straight off ``getUpdates`` or a
            webhook body.

    Never raises: an update with a missing ``chat``, a non-integer id or a
    shape from a future API version is ``None``, logged at debug. The caller
    still has ``update["update_id"]`` and can advance past it.
    """
    update_id = _int_or_none(update.get("update_id"))
    if update_id is None:
        logger.debug("telegram update for bot %r has no update_id; ignored", bot)
        return None

    payload: dict[str, Any] | None = None
    edited = False
    for key, is_edit in _MESSAGE_KEYS:
        candidate = update.get(key)
        if isinstance(candidate, dict):
            payload, edited = candidate, is_edit
            break
    if payload is None:
        logger.debug(
            "telegram update %d for bot %r carries no message payload; ignored", update_id, bot
        )
        return None

    chat = _dict_or_empty(payload.get("chat"))
    chat_id = _int_or_none(chat.get("id"))
    message_id = _int_or_none(payload.get("message_id"))
    if chat_id is None or message_id is None:
        logger.debug(
            "telegram update %d for bot %r has no usable chat/message id; ignored", update_id, bot
        )
        return None

    sender = _dict_or_empty(payload.get("from"))
    text = _str_or_none(payload.get("text")) or _str_or_none(payload.get("caption")) or ""
    reply_to_id = _int_or_none(_dict_or_empty(payload.get("reply_to_message")).get("message_id"))

    return InboundMessage(
        bot=bot,
        update_id=update_id,
        message_id=message_id,
        chat_id=chat_id,
        chat_type=str(chat.get("type") or "unknown"),
        chat_title=_str_or_none(chat.get("title")),
        chat_username=_str_or_none(chat.get("username")),
        sender_id=_int_or_none(sender.get("id")),
        sender_username=_str_or_none(sender.get("username")),
        sender_name=_full_name(sender),
        text=text,
        attachments=_attachments(payload),
        date=float(payload.get("date") or 0),
        reply_to_message_id=reply_to_id,
        edited=edited,
    )


__all__ = ["normalise_update"]
