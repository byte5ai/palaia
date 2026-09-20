"""Routing by origin (issue #411): which destination claims a ``(bot, chat)``.

**Specificity decides, not order.** A message is matched against three keys
in turn — the chat's numeric id, its public ``@name``, then the bot's
wildcard — and the first rule found wins. That is the whole algorithm, and
it is a deliberate non-feature that ``config.yaml``'s list order does not
enter into it: an operator appending a catch-all route to the bottom of the
file and an operator putting it at the top must get the same delivery, or
the routing table is a trap.

**Never across bots.** Every rule names a bot, and the wildcard is a wildcard
over *chats within one bot* only. The issue's whole point is that "a message
that arrived through the 'support' bot in the 'ops' channel can land
somewhere else than one through the 'personal' bot in a direct chat" — a
cross-bot wildcard would quietly undo that the first time someone added a
second bot.
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import CHAT_WILDCARD, InboundMessage, TelegramRoute


class RoutingTable:
    """Resolves ``(bot, chat)`` to the route that claims it.

    Built once per configuration (and rebuilt when the operator edits it),
    not per message: the index below is what makes a lookup three dict hits
    instead of a scan over every rule for every message.
    """

    def __init__(self, routes: Iterable[TelegramRoute]) -> None:
        self._by_key: dict[tuple[str, str], TelegramRoute] = {}
        for route in routes:
            self._by_key[(route.bot, route.chat)] = route

    @property
    def routes(self) -> list[TelegramRoute]:
        """Every rule, in insertion order — for the dashboard and for
        ``telegram_list_chats``."""
        return list(self._by_key.values())

    def candidates(self, *, chat_id: str, chat_username: str | None) -> list[str]:
        """The chat keys tried for this message, most specific first.

        Exposed (rather than kept private to :meth:`resolve`) because it is
        exactly what an operator staring at a ``telegram.message.dropped``
        event needs to see: *these* are the three rules that would have
        matched, and none of them exists.
        """
        keys = [chat_id]
        if chat_username:
            keys.append(f"@{chat_username.lower()}")
        keys.append(CHAT_WILDCARD)
        return keys

    def resolve(self, message: InboundMessage) -> TelegramRoute | None:
        """The route claiming ``message``, or ``None`` if nothing does."""
        for key in self.candidates(
            chat_id=message.chat_ref, chat_username=message.chat_username
        ):
            route = self._by_key.get((message.bot, key))
            if route is not None:
                return route
        return None

    def for_bot(self, bot: str) -> list[TelegramRoute]:
        """Every rule belonging to ``bot``."""
        return [route for key, route in self._by_key.items() if key[0] == bot]


__all__ = ["RoutingTable"]
