"""Builds one vault's memory tool family as a mountable FastMCP server.

Deliverable #2 of SPEC-105: search / read / write / edit / move / delete /
list / recent_activity, mounted once per configured vault (see
:mod:`palaia_hub.gateway.build`). SPEC-107 adds two more tools to the same
server — ``capture`` and ``inbox_status`` (the inbox/capture contract,
``v3/docs/vault-format.md`` §7); their composition logic lives in
:mod:`palaia_hub.gateway.inbox`. SPEC-106 adds two more — ``recall`` and
``build_context`` — backed by :mod:`palaia_hub.recall`; both are read-only,
and both take the same ergonomics treatment as everything else here.
Deliverable #4 (tool ergonomics) is implemented here directly on each tool:

- **Behavior annotations** (``readOnlyHint``/``destructiveHint``/
  ``idempotentHint``) on every tool.
- **Alias absorption**: ``search``'s ``query`` accepts ``q``/``text``;
  every ``folder`` parameter accepts ``dir``/``path``; ``ref`` accepts
  ``permalink``/``memory``/``uri``/``url`` and ``model`` accepts
  ``model_id``/``provider`` — via pydantic ``AliasChoices``. The
  published input schema still shows only the canonical name (verified in
  ``tests/gateway/test_memory_tools.py``); the aliases are absorbed
  silently, not documented as alternatives, so the schema an agent reads
  stays uncluttered.
- **Dual text/json output**: every tool returns a ``ToolResult`` with a
  human-readable ``content`` string and a ``structured_content`` payload
  (the underlying pydantic result model) side by side in the same
  response — not a client-selectable mode.
- **Leading purpose line**: every tool description starts with the vault's
  ``purpose`` string verbatim, so a client's tool picker always shows why
  this vault exists first (MASTERPLAN §5.2 disambiguation-from-the-tool-
  surface requirement).
- **IDENTITY instructions + `ai_assistant_guide` resource**: the server's
  ``instructions`` open with an ``IDENTITY:`` line naming the vault, and an
  ``ai_assistant_guide`` resource gives the model a short workflow guide
  (research/basic-memory.md §7).

Errors from the :class:`VaultService` (not-found, etc.) become
``ToolResult(is_error=True, ...)`` rather than an uncaught exception, per
MCP convention (isError, not a transport-level failure).

Issue #301 (Smart Nudges) adds one more thing to every *successful* result:
deterministic guidance, when there is any. Each success path goes through
:func:`_ok` instead of constructing its own ``ToolResult``, which runs the
detectors in :mod:`palaia_hub.nudges` over the result the call just produced
and attaches what the rate policy allows. Nothing extra is read or computed
to make that decision, and a call that trips no detector returns exactly the
``ToolResult`` it did before.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools.base import ToolResult
from mcp.types import ToolAnnotations
from pydantic import AliasChoices, BaseModel, Field

from ..auth.enforcement import missing_scope_error
from ..nudges import NudgeEngine
from ..recall import budget as recall_budget
from ..recall.models import ContextResult, RecallResult
from ..recall.service import DEFAULT_RECALL_LIMIT, recall_text, render_context
from ..recall.traversal import DEFAULT_DEPTH, MAX_DEPTH
from .apps.recall_app import RESOURCE_URI as RECALL_EXPLORER_URI
from .apps.review_app import RESOURCE_URI as REVIEW_QUEUE_URI
from .config import VaultMountConfig
from .guidance import current_session_key, nudged_result
from .inbox import missing_capture_fields, missing_fields_message
from .naming import compose_tool_name
from .vault_protocol import (
    CaptureResult,
    EffectiveSearchMode,
    InboxStatusResult,
    NoteRecord,
    NoteSummary,
    RequestedSearchMode,
    ReviewDecideResult,
    ReviewQueueResult,
    SearchHit,
    VaultService,
    VaultServiceError,
)

# --- alias-absorbing parameter types ---------------------------------------
# SPEC-105 deliverable #4 names these two alias groups explicitly: a query
# parameter that also accepts q/text, and a folder parameter that also
# accepts dir/path. AliasChoices only affects *validation* (what an
# incoming call is allowed to name the field) — the tool's published input
# schema still shows just "query"/"folder" (see docstring above), so the
# canonical shape a well-behaved client sees stays clean while a client
# that guesses "q" or "path" still succeeds.
QueryParam = Annotated[
    str,
    Field(
        validation_alias=AliasChoices("query", "q", "text"),
        description="Search text.",
    ),
]
OptionalQueryParam = Annotated[
    str,
    Field(
        default="",
        validation_alias=AliasChoices("query", "q", "text"),
        description="What you are looking for, in your own words.",
    ),
]
FolderParam = Annotated[
    str,
    Field(
        default="",
        validation_alias=AliasChoices("folder", "dir", "path"),
        description=(
            "Vault folder, e.g. 'projects/api'. Empty means the vault root "
            "(write/move) or the whole vault (list); for list the match is "
            "exact, subfolders excluded."
        ),
    ),
]
PermalinkParam = Annotated[
    str,
    Field(description="The note's permalink (alias, exact title or path also work)."),
]
LimitParam = Annotated[
    int,
    Field(description="Maximum results to return, best or most recent first."),
]
# SPEC-106's own alias groups, same principle as the two above. A
# `memory://` reference is the parameter models most often misname (they
# reach for `permalink`, `memory`, `uri` or `url` — all of which mean the
# same thing here), and the calling model's identity arrives as `model`,
# `model_id` or `provider` depending on the client.
RefParam = Annotated[
    str,
    Field(
        default="",
        validation_alias=AliasChoices("ref", "permalink", "memory", "uri", "url"),
        description=(
            "A memory:// reference to start from: a permalink, alias, title, "
            "path, memory:// URL, or a glob like 'projects/api-*'."
        ),
    ),
]
ModelParam = Annotated[
    str,
    Field(
        default="",
        validation_alias=AliasChoices("model", "model_id", "provider"),
        description=(
            "The calling model, as 'provider/model' (e.g. 'anthropic/opus-5') "
            "or just 'provider'. Selects per-model observation variants; "
            "omitting it serves the default phrasing."
        ),
    ),
]


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit]

    mode: RequestedSearchMode = "hybrid"
    """The search mode that was asked for."""

    effective_mode: EffectiveSearchMode = "hybrid"
    """The mode that actually ran — ``fts`` when a hybrid query had no
    vectors to work with, ``scan`` when no index was open at all."""

    degraded: bool = False
    degraded_reason: str = ""
    """SPEC-104's honesty signal, passed through so an agent can weigh the
    hits accordingly: a hybrid query answered from full-text alone says so
    (and each hit's ``matched`` names the channel that found it)."""

    pick_tool: str = ""
    """SPEC-208: this vault's mounted ``recall_pick`` tool name — see
    ``vault_protocol.ReviewQueueResult``'s docstring for why the
    recall-explorer app's "add to context" action learns its callback name
    from here rather than the mount namespace directly."""


class RecallPickResult(BaseModel):
    """What one ``recall_pick`` call answers: the full content of exactly
    the refs the caller (the recall-explorer app, on the user's behalf)
    asked for — SPEC-208's selective-context mechanism."""

    notes: list[NoteRecord]


class ListResult(BaseModel):
    folder: str
    notes: list[NoteSummary]


class RecentActivityResult(BaseModel):
    notes: list[NoteSummary]


class DeleteResult(BaseModel):
    permalink: str
    deleted: bool


def _error_result(exc: VaultServiceError) -> ToolResult:
    return ToolResult(content=str(exc), is_error=True)


def _note_text(verb: str, note: NoteRecord) -> str:
    return f"{verb}: {note.title!r} ({note.permalink})"


def vault_identity_block(vault: VaultMountConfig) -> str:
    """The IDENTITY line + short workflow guide for one vault.

    Used both for that vault's own tool server's ``instructions`` (a client
    that connects to the vault server directly — e.g. in tests — sees this)
    and, concatenated across every vault a profile mounts, for that
    profile's own ``instructions`` (what a real client connecting to
    ``/mcp/<profile>`` actually receives at ``initialize`` — ``mount()``
    does not propagate a mounted server's ``instructions`` to its parent,
    so the profile builder in ``build.py`` composes this explicitly rather
    than leaving real clients with no IDENTITY line at all).
    """
    identity = f"IDENTITY: this is the {vault.name!r} memory vault. {vault.purpose}"
    return (
        f"{identity}\n"
        "Something YOU learned this session (a decision, a preference, a "
        "correction, a fact worth keeping) goes in with capture, right away — "
        "no search, no placement decision; the curator files it. When the "
        "USER asks for a note, search first — check whether it already "
        "exists before creating a new one. Use recall to get what this vault "
        "knows about a topic (ranked, with shared values resolved) and "
        "build_context to pick up where a previous session left off. Use "
        "recent_activity to catch up on what changed since you last looked. "
        "Read the ai_assistant_guide resource for the full tool-by-tool "
        "workflow."
    )


def build_vault_server(
    vault: VaultMountConfig,
    service: VaultService,
    *,
    nudges: NudgeEngine | None = None,
) -> FastMCP:
    """Build the memory tool family for one vault, backed by ``service``.

    The returned server's tools are named exactly the eight base action
    names (``search``, ``read``, ...) — callers mount it with
    ``namespace=vault.namespace`` (see :mod:`palaia_hub.gateway.build`),
    which is what actually produces the vault-identity-carrying final name
    (``work_memory_search``). Building the tool names here without any
    namespace baked in keeps this function reusable across profiles: the
    same server object mounts into every profile that includes this vault.

    ``nudges`` is this vault's Smart Nudge engine (issue #301), created here
    by default and injectable for tests. One engine per vault server is the
    right granularity: the same server object is what mounts into every
    profile carrying this vault, so its rate-limit state follows the vault
    rather than fragmenting per profile, and a nudge about *this* vault's
    inbox is never suppressed by one about another's.
    """
    purpose = vault.purpose
    server = FastMCP(
        name=f"palaia-vault-{vault.key}",
        instructions=vault_identity_block(vault),
    )
    engine = nudges if nudges is not None else NudgeEngine(session_key=current_session_key)

    def desc(detail: str) -> str:
        return f"{purpose}\n\n{detail}"

    def _ok(action: str, text: str, payload: BaseModel) -> ToolResult:
        """A successful result for ``action``, plus any guidance it earned."""
        return nudged_result(
            engine, action=action, text=text, payload=payload, vault_key=vault.key
        )

    def _note_ok(action: str, verb: str, note: NoteRecord) -> ToolResult:
        return _ok(action, _note_text(verb, note), note)

    def scope_error(action: str) -> ToolResult | None:
        """``None`` if this call's token (if any) covers ``action``; else a
        ready-to-return ``ToolResult(is_error=True)`` naming the missing
        scope (SPEC-108 — see :func:`palaia_hub.auth.enforcement.
        missing_scope_error` for what "if any" means here).
        """
        message = missing_scope_error(vault.key, action)
        return ToolResult(content=message, is_error=True) if message else None

    # SPEC-208: this vault's own mounted names for the two MCP-Apps backend
    # actions, computed once here (not per-call) since `vault.namespace` is
    # fixed at construction time. Neither `recall_pick` nor `review_decide`
    # is in MEMORY_TOOL_ACTIONS, so neither is renameable via
    # `tool_renames` (same as `recall`/`build_context`/`capture`/
    # `inbox_status` before them) — the mounted name is always exactly the
    # namespace-composed one.
    recall_pick_tool_name = compose_tool_name(vault.namespace, "recall_pick")
    review_decide_tool_name = compose_tool_name(vault.namespace, "review_decide")

    @server.tool(
        name="search",
        description=desc(
            "Search this vault's notes. Returns best matches first. Each hit "
            "reports which retrieval channel found it ('text' = full-text/BM25, "
            "'meaning' = semantic/vector, both = found by both) plus that "
            "channel's rank; the result reports the search mode that actually "
            "ran and whether it was degraded (e.g. semantic search unavailable, "
            "answered from full-text alone) — weigh the hits accordingly."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=RECALL_EXPLORER_URI),
    )
    async def search(query: QueryParam, limit: LimitParam = 10) -> ToolResult:
        if (err := scope_error("search")) is not None:
            return err
        response = await service.search(query, limit=limit)
        hits = response.hits
        text = (
            f"{len(hits)} match(es) for {query!r}: "
            + ", ".join(
                f"{h.title!r} ({h.permalink}, via {'+'.join(h.matched) or 'unknown'})"
                for h in hits
            )
            if hits
            else f"no matches for {query!r}"
        )
        # The degraded note rides in the human-readable half too: a model
        # that only reads `content` should not have to infer that this
        # answer came from full-text alone.
        if response.degraded:
            text += (
                f"\n[degraded: {response.mode} search ran as "
                f"{response.effective_mode} — {response.degraded_reason}]"
            )
        result = SearchResult(
            query=query,
            hits=hits,
            mode=response.mode,
            effective_mode=response.effective_mode,
            degraded=response.degraded,
            degraded_reason=response.degraded_reason,
            pick_tool=recall_pick_tool_name,
        )
        return _ok("search", text, result)

    @server.tool(
        name="read",
        description=desc(
            "Read one note in full. `permalink` also accepts the note's alias, "
            "exact title or vault path; an unknown or ambiguous reference is an "
            "error. The text result shows value references resolved to their "
            "current values; structured_content.body is the note as written — "
            "use that as the base for edit."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def read(permalink: PermalinkParam) -> ToolResult:
        if (err := scope_error("read")) is not None:
            return err
        try:
            note = await service.read(permalink)
        except VaultServiceError as exc:
            return _error_result(exc)
        # The human-readable half shows value references resolved to their
        # current source values (format spec §5.3): a model reading a note
        # should see what the rate limit *is*, not that there is an embed
        # pointing at it. `structured_content.body` stays the note as
        # written, for anything about to edit it.
        return _ok("read", note.resolved_body or note.body, note)

    @server.tool(
        name="write",
        description=desc(
            "Create a new note the user asked for, at `<folder>/<slugified "
            "title>.md`. If a note already exists at that path the call fails "
            "rather than overwriting — search first and edit the existing note "
            "instead. Knowledge you picked up yourself goes through capture."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def write(
        title: Annotated[
            str, Field(description="Note title; also sets the file name (slugified).")
        ],
        body: Annotated[str, Field(description="Markdown body.")],
        folder: FolderParam = "",
        type: Annotated[  # noqa: A002 - matches the vault-format field name
            str,
            Field(
                description=(
                    "Frontmatter type. Default 'note'; 'meta' notes are hidden "
                    "from search, list and recent_activity."
                )
            ),
        ] = "note",
        tags: Annotated[
            list[str] | None, Field(description="Tags to set. Omit for none.")
        ] = None,
    ) -> ToolResult:
        if (err := scope_error("write")) is not None:
            return err
        try:
            note = await service.write(title, body, folder=folder, type=type, tags=tags)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_ok("write", "created", note)

    @server.tool(
        name="edit",
        description=desc(
            "Update an existing note. `body` replaces the whole body; `append` "
            "adds text on a new line after the (possibly replaced) body; `tags` "
            "replaces the full tag list. Omitted fields keep their current value."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    )
    async def edit(
        permalink: PermalinkParam,
        body: Annotated[
            str | None, Field(description="New body, replacing the current one.")
        ] = None,
        append: Annotated[
            str | None, Field(description="Text appended on a new line after the body.")
        ] = None,
        tags: Annotated[
            list[str] | None, Field(description="New tags, replacing the whole list.")
        ] = None,
    ) -> ToolResult:
        if (err := scope_error("edit")) is not None:
            return err
        try:
            note = await service.edit(permalink, body=body, append=append, tags=tags)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_ok("edit", "updated", note)

    @server.tool(
        name="move",
        description=desc("Move a note to a different folder. Its permalink never changes."),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def move(permalink: PermalinkParam, folder: FolderParam = "") -> ToolResult:
        if (err := scope_error("move")) is not None:
            return err
        try:
            note = await service.move(permalink, folder)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _note_ok("move", "moved", note)

    @server.tool(
        name="delete",
        description=desc(
            "Delete a note by permalink. Irreversible outside git history. A "
            "reference that matches no note returns deleted=false, not an error."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
    )
    async def delete(permalink: PermalinkParam) -> ToolResult:
        if (err := scope_error("delete")) is not None:
            return err
        deleted = await service.delete(permalink)
        text = f"deleted {permalink!r}" if deleted else f"nothing to delete at {permalink!r}"
        return _ok("delete", text, DeleteResult(permalink=permalink, deleted=deleted))

    @server.tool(
        name="list",
        description=desc(
            "List note summaries (permalink, title, type, tags, folder, modified "
            "— no bodies), sorted by permalink. With `folder`, only notes "
            "directly in that folder are listed (subfolders are not included). "
            "`meta` notes are excluded."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def list_notes(folder: FolderParam = "") -> ToolResult:
        if (err := scope_error("list")) is not None:
            return err
        notes = await service.list_notes(folder=folder)
        text = f"{len(notes)} note(s)" + (f" in {folder!r}" if folder else "")
        return _ok("list", text, ListResult(folder=folder, notes=notes))

    @server.tool(
        name="recent_activity",
        description=desc(
            "The most recently modified notes, most recent first, up to "
            "`limit`. Summaries only (no bodies); `meta` notes are excluded."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def recent_activity(limit: LimitParam = 10) -> ToolResult:
        if (err := scope_error("recent_activity")) is not None:
            return err
        notes = await service.recent_activity(limit=limit)
        text = f"{len(notes)} recently modified note(s)"
        return _ok("recent_activity", text, RecentActivityResult(notes=notes))

    @server.tool(
        name="recall",
        description=desc(
            "Recall what matters about a topic or a specific note. Prefer "
            "this over search when you want to *use* what the vault knows: "
            "results are ranked by relevance plus recency, how often they "
            "are used, and how load-bearing they are; shared values are "
            "resolved to their current source; and rules phrased per model "
            "family arrive already narrowed to yours. Pass a query, or a ref "
            "(permalink/title/memory:// URL/glob) when you know the address."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=RECALL_EXPLORER_URI),
    )
    async def recall(
        query: OptionalQueryParam = "",
        ref: RefParam = "",
        limit: Annotated[
            int, Field(description="How many results to return, best first.")
        ] = DEFAULT_RECALL_LIMIT,
        model: ModelParam = "",
    ) -> ToolResult:
        if (err := scope_error("recall")) is not None:
            return err
        try:
            result = await service.recall(query=query, ref=ref, limit=limit, model=model)
        except VaultServiceError as exc:
            return _error_result(exc)
        result = result.model_copy(update={"pick_tool": recall_pick_tool_name})
        return _ok("recall", recall_text(result), result)

    @server.tool(
        name="build_context",
        description=desc(
            "Assemble the context around a starting point: resolve it, walk "
            "its relations to `depth` hops, and return one deduplicated, "
            "token-budgeted package. This is the 'continue where we left "
            "off' tool — it follows the links the notes actually declare "
            "instead of re-searching. Notes that do not fit `max_tokens` are "
            "shortened to their title plus key facts, never cut mid-note. "
            f"`depth` is capped at {MAX_DEPTH}; `timeframe` ('30d', '2w', or "
            "an ISO date) keeps the walk to what is still current."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def build_context(
        ref: RefParam = "",
        query: OptionalQueryParam = "",
        depth: Annotated[
            int,
            Field(
                description=(
                    f"Relation hops to walk from the starting point, 0-{MAX_DEPTH}. "
                    "1 is 'this note and what it names'."
                )
            ),
        ] = DEFAULT_DEPTH,
        timeframe: Annotated[
            str,
            Field(
                description=(
                    "Only include notes at least this recent: '30d', '2w', '12h', "
                    "or an ISO date. Empty means no time limit."
                )
            ),
        ] = "",
        max_tokens: Annotated[
            int,
            Field(
                description=(
                    "Token budget for the whole package. Notes that do not fit "
                    "are summarized, then named — never cut mid-note."
                )
            ),
        ] = recall_budget.DEFAULT_MAX_TOKENS,
        model: ModelParam = "",
    ) -> ToolResult:
        if (err := scope_error("build_context")) is not None:
            return err
        try:
            result = await service.build_context(
                ref=ref,
                query=query,
                depth=depth,
                timeframe=timeframe,
                max_tokens=max_tokens,
                model=model,
            )
        except VaultServiceError as exc:
            return _error_result(exc)
        return _ok("build_context", render_context(result), result)

    @server.tool(
        name="capture",
        description=desc(
            "Save something you (the assistant) learned this session — a "
            "decision, a preference, a correction, a fact worth keeping — as an "
            "uncurated inbox/ note (format spec §7). No placement decision is "
            "needed; the curator later files, deduplicates and structures it. "
            "An identical capture is acknowledged with duplicate=true and not "
            "written again. For notes the user explicitly asked for, use "
            "write/edit instead."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False
        ),
    )
    async def capture(
        what_it_concerns: Annotated[
            str | None,
            Field(
                description=(
                    "Required. The topic or entity this is about; becomes the "
                    "note title, e.g. 'API Gateway'."
                )
            ),
        ] = None,
        why_keep: Annotated[
            str | None,
            Field(
                description=(
                    "Required. Why it is worth keeping — what goes wrong if it is forgotten."
                )
            ),
        ] = None,
        content: Annotated[
            str | None,
            Field(
                description=(
                    "Required. The knowledge itself, understandable without this conversation."
                )
            ),
        ] = None,
        source: Annotated[
            str | None,
            Field(description="Where this came from. Defaults to 'agent capture, <date>'."),
        ] = None,
    ) -> ToolResult:
        if (err := scope_error("capture")) is not None:
            return err
        missing = missing_capture_fields(
            what_it_concerns=what_it_concerns, why_keep=why_keep, content=content
        )
        if missing:
            return ToolResult(content=missing_fields_message(missing), is_error=True)
        assert what_it_concerns is not None
        assert why_keep is not None
        assert content is not None
        try:
            result = await service.capture(
                what_it_concerns=what_it_concerns,
                why_keep=why_keep,
                content=content,
                source=source,
            )
        except VaultServiceError as exc:
            return _error_result(exc)
        text = (
            f"already captured as {result.permalink!r} (capture_id {result.capture_id}) "
            "— duplicate acknowledged, nothing new written"
            if result.duplicate
            else f"captured to {result.permalink!r} (capture_id {result.capture_id})"
        )
        return _ok("capture", text, result)

    @server.tool(
        name="inbox_status",
        description=desc(
            "Inbox health: how many uncurated captures are waiting, the "
            "oldest entry's age, and the most recent capture."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True),
    )
    async def inbox_status() -> ToolResult:
        if (err := scope_error("inbox_status")) is not None:
            return err
        status = await service.inbox_status()
        text = f"{status.count} uncurated capture(s)"
        if status.oldest_age_seconds is not None:
            text += f", oldest {status.oldest_age_seconds:.0f}s old"
        if status.last_capture_id:
            text += f", last capture {status.last_capture_id!r}"
        return _ok("inbox_status", text, status)

    @server.tool(
        name="review_queue",
        description=desc(
            "List every curator maintenance proposal awaiting review "
            "(format spec §8) — the review-queue app's data source. Each "
            "proposal is a card: title, status, and its full body (a "
            "human-readable explanation, sometimes with a diff/plan)."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
        app=AppConfig(resource_uri=REVIEW_QUEUE_URI),
    )
    async def review_queue() -> ToolResult:
        if (err := scope_error("review_queue")) is not None:
            return err
        result = await service.review_queue()
        result = result.model_copy(update={"decide_tool": review_decide_tool_name})
        text = f"{len(result.proposals)} proposal(s) awaiting review"
        return _ok("review_queue", text, result)

    @server.tool(
        name="review_decide",
        description=desc(
            "App-only action for the review-queue UI: approve or reject one "
            "curator proposal, flipping its frontmatter `status` (format "
            "spec §8) — the exact same effect as doing so in the dashboard "
            "or by editing the note directly. Only valid on a proposal "
            "whose status is currently 'proposed'."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False),
    )
    async def review_decide(
        permalink: Annotated[
            str, Field(description="Permalink of a proposal whose status is 'proposed'.")
        ],
        decision: Annotated[
            Literal["approved", "rejected"], Field(description="'approved' or 'rejected'.")
        ],
    ) -> ToolResult:
        if (err := scope_error("review_decide")) is not None:
            return err
        try:
            result = await service.review_decide(permalink, decision)
        except VaultServiceError as exc:
            return _error_result(exc)
        return _ok("review_decide", f"{permalink!r} marked {decision}", result)

    @server.tool(
        name="recall_pick",
        description=desc(
            "App-only helper for the recall-explorer UI: fetch the full "
            "content of one or more search/recall results the user "
            "selected, so only those enter the model's context — "
            "SPEC-208's selective-context mechanism, not a general-purpose "
            "batch-read tool."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
        ),
    )
    async def recall_pick(
        refs: Annotated[
            list[str],
            Field(
                description=(
                    "References of the notes to load; the call fails on the "
                    "first one that does not resolve."
                )
            ),
        ],
    ) -> ToolResult:
        if (err := scope_error("recall_pick")) is not None:
            return err
        notes: list[NoteRecord] = []
        for ref in refs:
            try:
                notes.append(await service.read(ref))
            except VaultServiceError as exc:
                return _error_result(exc)
        text = f"picked {len(notes)} note(s) for context"
        return _ok("recall_pick", text, RecallPickResult(notes=notes))

    @server.resource(
        f"guide://{vault.key}/ai_assistant_guide",
        name="ai_assistant_guide",
        mime_type="text/markdown",
    )
    def ai_assistant_guide() -> str:
        return (
            f"# {vault.name} memory vault — assistant guide\n\n"
            f"{purpose}\n\n"
            "## Workflow\n"
            "0. **recall** when you want to *use* what this vault knows — it "
            "ranks by relevance plus recency/usage/significance, resolves "
            "shared values to their current source, and narrows per-model "
            "rules to yours. **build_context** when resuming work: give it a "
            "starting note (or a query that finds one) and it walks the "
            "relations around it into one token-budgeted package.\n"
            "1. **capture** anything YOU learned along the way — a decision, "
            "a preference, a correction, a fact worth keeping. Do it the "
            "moment it appears, before answering; no search, no placement "
            "decision — the curator files it. **inbox_status** shows how "
            "much is waiting.\n"
            "2. When the USER asks for a note: **search** first — check "
            "whether it already exists before writing.\n"
            "3. **read** a hit's full body before deciding to edit vs. write new.\n"
            "4. **write** a new note when nothing matches; **edit** (replace or "
            "append) when something does. Both are for notes the user asked "
            "for — knowledge you picked up yourself goes in with capture "
            "(step 1), even when a related note exists.\n"
            "5. **list** / **recent_activity** to browse or catch up without a "
            "specific query.\n"
            "6. **move** relocates a note without changing its identity "
            "(permalink); **delete** removes it.\n"
            "7. **review_queue** lists curator proposals awaiting a human "
            "decision (format spec §8); **review_decide** and **recall_pick** "
            "are app-only helpers for the review-queue and recall-explorer "
            "MCP Apps, not something you would normally call directly.\n\n"
            "## Reading a search result\n"
            "`search` tells you *how* every hit was found, so you can weigh "
            "it: each hit's `matched` lists its retrieval channel(s) — "
            "`text` (full-text/BM25, the words are literally there) and/or "
            "`meaning` (semantic/vector, related without sharing the words) — "
            "and `fts_rank`/`vector_rank` give its rank within each channel "
            "(1-based, so 1 = that channel's best answer; unset means the "
            "channel did not produce this hit). A hit "
            "matched by both channels is the strongest signal there is.\n"
            "The result as a whole reports `mode` (asked for) vs. "
            "`effective_mode` (what ran: `hybrid`, `fts`, `vector`, or "
            "`scan` when no index is open) plus `degraded` and "
            "`degraded_reason`. `degraded: true` means you got less than you "
            "asked for — typically semantic search unavailable or still "
            "embedding, answered from full-text alone. Then a *missing* note "
            "is not evidence it does not exist: rephrase in the words the "
            "note would use, or try `recall`, before concluding anything.\n\n"
            "## Parameter notes\n"
            "`search`'s query, every `folder` parameter, and recall's `ref` / "
            "`model` accept a few common misnamings (e.g. `q`, `dir`, `path`, "
            "`permalink`, `provider`) — use the documented name shown in the "
            "tool schema when in doubt.\n"
            "`ref` takes any address form: a permalink, an alias, an exact "
            "title, a path, a `memory://` URL, a glob (`projects/api-*`), a "
            "block (`note#^anchor`) or a search result's sub-note ref. If two "
            "notes answer to the same name you get an error listing both — "
            "pick one by permalink rather than guessing."
        )

    return server


__all__ = ["build_vault_server", "vault_identity_block"]

# Re-exported for callers that want the result-model shapes without reaching
# into this module's internals (e.g. tests asserting structured_content).
_RESULT_MODELS: dict[str, type[Any]] = {
    "search": SearchResult,
    "list": ListResult,
    "recent_activity": RecentActivityResult,
    "delete": DeleteResult,
    "capture": CaptureResult,
    "inbox_status": InboxStatusResult,
    "recall": RecallResult,
    "build_context": ContextResult,
    "review_queue": ReviewQueueResult,
    "review_decide": ReviewDecideResult,
    "recall_pick": RecallPickResult,
}
