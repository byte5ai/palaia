"""The Telegram connector (issue #411): inbound messages routed per
bot/chat, outbound sending, exposed to agents as MCP tools.

Deliberately empty of imports, for the same reason
:mod:`palaia_hub.upstream`'s package ``__init__`` is:
:mod:`palaia_hub.config` imports :mod:`palaia_hub.telegram.models` directly
(the ``telegram:`` section of ``config.yaml`` *is* those models), and that
module must stay importable without dragging httpx, fastapi or fastmcp in
behind it. Import the submodule you need — ``palaia_hub.telegram.models``,
``.api``, ``.routing``, ``.service``, ``.poller``, ``.webhook`` — never this
package for its side effects.
"""

from __future__ import annotations

__all__: list[str] = []
