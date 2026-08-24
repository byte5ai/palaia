"""A scripted curation session: the fake LLM runner used by the curator tests.

SPEC-206 acceptance criterion #5 wants an end-to-end run "with a scripted
fake LLM runner (no real model in CI)". This is that runner — and it is a
*real* client of the curator profile: every call it makes goes through the
gateway's middleware, the memory tool family and the vault engine, exactly
like a model's would. Only the deciding is scripted.

Nothing here shortcuts the guards. A script that tries a forbidden call gets
the same refusal a model would (see ``lying_session`` and the guard matrix).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastmcp import Client, FastMCP

from palaia_hub.curator.models import SessionResult
from palaia_hub.curator.session import SessionRequest

#: A script: given a connected client and the session's request, do things.
Script = Callable[[Client, SessionRequest], Awaitable[None]]


@dataclass
class ScriptedSessionRunner:
    """Runs ``script`` against ``server`` instead of spawning a model.

    ``server_factory``, given, is called fresh on every :meth:`run` instead
    of connecting to the fixed ``server`` object — for a curator profile
    that gets *rebuilt* under a :class:`~palaia_hub.gateway.dynamic.
    DynamicGateway` (SPEC-301 deliverable #4: a vault added at runtime
    swaps in a brand-new profile server), so the scripted runner always
    talks to whichever generation is current, exactly the way a real
    session (HTTP, through a URL that always dispatches to the current
    mount) already does. ``server`` is still required as a fallback/type
    anchor and stays the only thing every pre-existing caller sets.
    """

    server: FastMCP
    script: Script
    stdout: str = ""
    exit_code: int = 0
    server_factory: Callable[[], FastMCP] | None = None
    #: Every request this runner was asked to run, in order — so a test can
    #: assert that an empty inbox launched no session at all.
    requests: list[SessionRequest] = field(default_factory=list)
    #: Every ``(tool, arguments, is_error, text)`` the script performed.
    calls: list[tuple[str, dict[str, object], bool, str]] = field(default_factory=list)

    async def run(self, request: SessionRequest) -> SessionResult:
        self.requests.append(request)
        server = self.server_factory() if self.server_factory is not None else self.server
        async with Client(server) as client:
            recorder = _RecordingClient(client, self.calls)
            await self.script(recorder, request)  # type: ignore[arg-type]
        return SessionResult(exit_code=self.exit_code, stdout=self.stdout)


class _RecordingClient:
    """Thin proxy that records every ``call_tool`` a script makes."""

    def __init__(
        self, client: Client, sink: list[tuple[str, dict[str, object], bool, str]]
    ) -> None:
        self._client = client
        self._sink = sink

    async def call_tool(
        self, name: str, arguments: dict[str, object] | None = None
    ) -> object:
        result = await self._client.call_tool(name, arguments or {}, raise_on_error=False)
        text = result.content[0].text if result.content else ""  # type: ignore[union-attr]
        self._sink.append((name, arguments or {}, bool(result.is_error), text))
        return result

    def __getattr__(self, item: str) -> object:  # pragma: no cover - passthrough
        return getattr(self._client, item)


def ingest_session(namespace: str, *, folder: str = "projects") -> Script:
    """A well-behaved session: search twice, then write one note with provenance."""

    async def script(client: Client, request: SessionRequest) -> None:
        await client.call_tool(f"{namespace}_search", {"query": "rate limit"})
        await client.call_tool(f"{namespace}_search", {"query": "ingest cap"})
        await client.call_tool(
            f"{namespace}_write",
            {
                "title": "API Gateway ingest limit",
                "body": (
                    "The ingest limit is 100 req/min.\n\n"
                    "- [limit] 100 req/min because the embed queue saturates above that\n"
                    f"- [source] inbox capture {request.capture_id}\n"
                ),
                "folder": folder,
            },
        )

    return script


def proposal_session(namespace: str) -> Script:
    """A conservative session: raise a proposal instead of rewriting a note."""

    async def script(client: Client, request: SessionRequest) -> None:
        await client.call_tool(f"{namespace}_search", {"query": "rate limit"})
        await client.call_tool(
            f"{namespace}_write",
            {
                "title": "Merge the two rate-limit notes",
                "body": (
                    "Two notes claim different ingest limits; merging them is a "
                    "rewrite, so here is the plan.\n\n"
                    f"- [source] inbox capture {request.capture_id}\n\n"
                    "```json plan\n"
                    '{"operations": [{"op": "append", "target": '
                    '"projects/api-gateway", "text": "- [limit] 100 req/min"}]}\n'
                    "```\n"
                ),
                "folder": "review",
                "type": "proposal",
            },
        )

    return script


def lying_session(namespace: str) -> Script:
    """A session that claims success and writes nothing that can be verified.

    It also *tries* the two calls the policy forbids — deleting the capture
    and editing it — so the test proves both that the guards refuse them and
    that the refusal does not become a false 'ingested'.
    """

    async def script(client: Client, request: SessionRequest) -> None:
        await client.call_tool(f"{namespace}_delete", {"permalink": "inbox/anything"})
        await client.call_tool(
            f"{namespace}_edit",
            {"permalink": "inbox/anything", "append": "- [note] curated, trust me"},
        )

    return script


def silent_session() -> Script:
    """A session that does nothing at all."""

    async def script(client: Client, request: SessionRequest) -> None:
        return None

    return script
