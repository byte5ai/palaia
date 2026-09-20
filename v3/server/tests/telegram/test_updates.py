"""Normalising a raw Telegram update (issue #411).

The property that matters most here is the *total* one: nothing raises, and
anything unrecognised is ``None`` — because the poller advances its offset
past whatever this returns, and an exception would wedge the loop on one bad
update forever.
"""

from __future__ import annotations

import pytest

from palaia_hub.telegram.updates import normalise_update

from .conftest import message_update


def test_a_plain_message_normalises_with_everything_a_route_needs() -> None:
    message = normalise_update("support", message_update(5, chat_id=-1001, text="ping"))
    assert message is not None
    assert (message.bot, message.update_id, message.chat_id) == ("support", 5, -1001)
    assert message.text == "ping"
    assert message.sender_name == "Ada Lovelace"
    assert message.sender_username == "ada"
    assert message.sender_label == "Ada Lovelace (@ada)"
    assert message.chat_label == "Ops"
    assert message.chat_ref == "-1001"
    assert message.edited is False


@pytest.mark.parametrize(
    ("key", "edited"),
    [
        ("message", False),
        ("channel_post", False),
        ("edited_message", True),
        ("edited_channel_post", True),
    ],
)
def test_all_four_message_shapes_normalise_and_record_whether_they_are_edits(
    key: str, edited: bool
) -> None:
    message = normalise_update("support", message_update(1, chat_id=-1, key=key))
    assert message is not None
    assert message.edited is edited


def test_a_caption_is_the_text() -> None:
    """A media message puts its words in ``caption``; a route that matched
    only ``text`` would silently skip every photo with a comment on it."""
    update = {
        "update_id": 9,
        "message": {
            "message_id": 3,
            "date": 1,
            "chat": {"id": -5, "type": "group"},
            "caption": "look at this",
            "photo": [
                {"file_id": "small", "file_unique_id": "u1", "file_size": 100},
                {"file_id": "large", "file_unique_id": "u2", "file_size": 900},
            ],
        },
    }
    message = normalise_update("support", update)
    assert message is not None
    assert message.text == "look at this"
    # Only the largest size, or one photo would look like an album of four.
    assert [(a.kind, a.file_id) for a in message.attachments] == [("photo", "large")]


def test_a_document_is_recorded_as_a_reference_not_downloaded() -> None:
    update = {
        "update_id": 10,
        "message": {
            "message_id": 4,
            "date": 1,
            "chat": {"id": -5, "type": "group"},
            "document": {
                "file_id": "doc1",
                "file_unique_id": "u9",
                "file_name": "notes.pdf",
                "mime_type": "application/pdf",
                "file_size": 2048,
            },
        },
    }
    message = normalise_update("support", update)
    assert message is not None
    attachment = message.attachments[0]
    assert attachment.kind == "document"
    assert attachment.file_name == "notes.pdf"
    assert attachment.file_size == 2048


def test_a_reply_carries_the_message_it_answers() -> None:
    update = message_update(11, chat_id=-7)
    update["message"]["reply_to_message"] = {"message_id": 99}
    message = normalise_update("support", update)
    assert message is not None
    assert message.reply_to_message_id == 99


@pytest.mark.parametrize(
    "update",
    [
        {},
        {"update_id": 1},
        {"update_id": 2, "callback_query": {"id": "abc"}},
        {"update_id": 3, "message": {"date": 1, "chat": {"id": -1, "type": "group"}}},
        {"update_id": 4, "message": {"message_id": 1, "date": 1}},
        {"update_id": 5, "message": "not an object"},
    ],
    ids=["empty", "no-payload", "callback-query", "no-message-id", "no-chat", "wrong-type"],
)
def test_anything_unusable_is_none_and_never_raises(update: dict) -> None:
    assert normalise_update("support", update) is None


def test_a_channel_post_without_a_sender_gets_an_honest_label() -> None:
    update = {
        "update_id": 12,
        "channel_post": {
            "message_id": 1,
            "date": 1,
            "chat": {"id": -100, "type": "channel", "username": "announcements"},
            "text": "release notes",
        },
    }
    message = normalise_update("support", update)
    assert message is not None
    assert message.sender_id is None
    assert message.sender_label == "(channel)"
    assert message.chat_label == "@announcements"


def test_metadata_never_carries_the_text() -> None:
    """The bus rule, asserted on the shape rather than at each call site."""
    message = normalise_update("support", message_update(1, chat_id=-1, text="secret plans"))
    assert message is not None
    metadata = message.metadata()
    assert "text" not in metadata
    assert metadata["text_chars"] == len("secret plans")
    assert "secret plans" not in repr(metadata)
