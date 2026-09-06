"""Issue #364, seen from the messenger: mail survives its recipient's silence."""

from __future__ import annotations

import pytest

from palaia_hub.directory.service import DirectoryService
from palaia_hub.directory.store import PRUNE_TTL_MULTIPLIER
from palaia_hub.messenger.models import UnknownRecipientError
from palaia_hub.messenger.service import MessengerService
from palaia_hub.messenger.store import MessengerStore

from .conftest import Clock

pytestmark = pytest.mark.anyio


async def test_a_session_pruned_from_the_directory_can_still_read_its_mail(
    clock: Clock, directory: DirectoryService, store: MessengerStore
) -> None:
    service = MessengerService(store, directory)
    sender = await directory.register(scope="a", ttl_seconds=60)
    quiet = await directory.register(scope="b", ttl_seconds=60)
    sent = await service.send(
        sender=sender.session.handle,
        session_secret=sender.session_secret,
        message_type="request",
        to=quiet.session.handle,
        subject="still here?",
        body="please answer within the week",
        ttl_seconds=7 * 24 * 3600,
    )

    # The recipient misses five heartbeats: pruned from every listing.
    clock.advance(60 * PRUNE_TTL_MULTIPLIER + 1)
    assert quiet.session.handle not in {s.handle for s in (await directory.list()).sessions}

    result = await service.check(quiet.session.handle, quiet.session_secret)

    assert [envelope.id for envelope in result.envelopes] == [sent.envelopes[0].id]
    assert result.envelopes[0].body == "please answer within the week"

    # ...but nobody can send it anything new until it comes back.
    with pytest.raises(UnknownRecipientError):
        await service.send(
            sender=sender.session.handle,
            session_secret=sender.session_secret,
            message_type="inform",
            to=quiet.session.handle,
            subject="new",
        )
