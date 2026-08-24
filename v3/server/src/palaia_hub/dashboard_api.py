"""Dashboard REST surface for the wizard and the memory explorer (SPEC-110).

SPEC-109 built the shell and the always-on ``/api/health``/``/api/info``/
``/api/events`` routes; SPEC-107/108 added the opt-in inbox-status and
token-management surfaces. This module is the last opt-in piece: the two
screens that need an API SPEC-109 never built — the onboarding wizard's
"first vault" step, and the memory explorer's folder tree / note view /
local graph. Mounted by :func:`palaia_hub.app.create_app` only when it is
given a ``vault_registry`` (a :class:`~palaia_hub.vault.VaultRegistry`),
same opt-in pattern as ``gateway``/``token_store`` — a caller that only
needs the MCP surface, or only the inbox-status endpoint, does not gain an
unused router.

SPEC-208 adds the review queue's REST mirror here too (``GET .../review``,
``POST .../review/{permalink}/decision``): the future dashboard
review-queue screen and the review-queue MCP App both end up calling the
same :meth:`~palaia_hub.gateway.vault_protocol.VaultService.review_decide`
underneath, so "approve from the app" and "approve from the dashboard" are
one code path, not two that could drift.

Every route talks to the real vault engine through
:class:`~palaia_hub.gateway.wiring.EngineVaultService` (SPEC-113's
adapter) for the actions that protocol already covers (list/read/search);
history and the local link graph reach past that protocol into the engine
directly, because :class:`~palaia_hub.gateway.vault_protocol.VaultService`
has no method for either (by design — see that module's docstring: it is
the narrow surface the *memory tools* need, not the dashboard's).

**Local graph, not a global hairball** (SPEC-110's deliverable #2): outbound
links come from scanning the note's own body with
:func:`palaia_hub.vault.links.iter_links`; inbound links come from a linear
scan of every other note's body for a link that resolves back to this note
— the same trade-off :class:`EngineVaultService.search` already makes (no
SPEC-104 index exists yet). A link that resolves to nothing yet (format
spec: "linked before it exists") is silently skipped rather than treated as
an error — it is not a graph edge until the target note exists.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .curator.profile import CURATOR_PROFILE_PATH
from .curator.wiring import CuratorWiring
from .gateway.config import DEFAULT_GATEWAY_PROFILE, VaultMountConfig
from .gateway.dynamic import DynamicGateway
from .gateway.vault_protocol import (
    NoteRecord,
    NoteSummary,
    ReviewDecideResult,
    ReviewQueueResult,
    SearchHit,
    VaultServiceError,
)
from .gateway.wiring import EngineVaultService
from .index import IndexStatus, VaultIndex, embed_progress
from .vault import (
    AmbiguousReferenceError,
    CommitInfo,
    InvalidPathError,
    NoteNotFoundError,
    VaultConfigError,
    VaultEngine,
    VaultInfo,
    VaultNotFoundError,
    VaultRegistry,
)
from .vault import permalink as pl
from .vault.links import iter_links

# Two starter notes offered by the wizard's "start from a template" switch
# (deliverable #1). Deliberately small and deletable — a template is a
# learning aid, never a dependency (onboarding.html: "Deletable, no
# lock-in."). The welcome note's wikilink to itself would be silly, so the
# example note links to it instead, demonstrating that a link works before
# its target note is read again.
_TEMPLATE_NOTES: tuple[tuple[str, str], ...] = (
    (
        "Welcome to this vault",
        "This is a starter note so the vault is not empty on day one.\n\n"
        "Delete it whenever you like — nothing here is load-bearing. Connect "
        "a client and ask it to remember something, or write your first real "
        "note yourself from the explorer.\n",
    ),
    (
        "Example project",
        "An example of what a note can look like: a title, a folder, and "
        "whatever you want to say. Link to another note with two square "
        "brackets around its title, like [[Welcome to this vault]] — the "
        "link resolves even if you write the target note later.\n",
    ),
)


class VaultOut(BaseModel):
    """One registered vault (registry name + manifest-declared identity)."""

    model_config = ConfigDict(extra="forbid")

    key: str
    purpose: str | None = None
    path: str
    writable: bool
    note_count: int


class CreateVaultRequest(BaseModel):
    """The wizard's "first vault" step, and any later "add a vault" call."""

    model_config = ConfigDict(extra="forbid")

    key: str
    purpose: str | None = None
    #: Absolute directory for the vault's files. Omitted (the common case,
    #: the wizard never asks for a path unless the owner clicks "Change…")
    #: defaults to ``<hub home>/vaults/<key>``.
    path: str | None = None
    #: Seed the two starter notes above (onboarding.html's "Start from a
    #: template" switch).
    template: bool = False


class ReviewDecisionRequest(BaseModel):
    """The review-queue screen's approve/reject action (SPEC-208, format
    spec §8) — the identical decision the review-queue MCP App's
    ``review_decide`` tool makes, through the same
    :meth:`~palaia_hub.gateway.vault_protocol.VaultService.review_decide`
    call, so both paths flip a proposal's status the exact same way."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class CommitOut(BaseModel):
    """One git commit from a note's history (explorer's "History" panel)."""

    model_config = ConfigDict(extra="forbid")

    sha: str
    subject: str
    author_name: str
    committed_at: str

    @classmethod
    def from_commit(cls, commit: CommitInfo) -> CommitOut:
        return cls(
            sha=commit.sha,
            subject=commit.subject,
            author_name=commit.author_name,
            committed_at=commit.committed_at.isoformat(),
        )


class GraphNodeOut(BaseModel):
    """One node in a note's local graph — enough to link to it."""

    model_config = ConfigDict(extra="forbid")

    permalink: str
    title: str


class LocalGraphOut(BaseModel):
    """A note's one-hop neighborhood: what it links to, what links to it."""

    model_config = ConfigDict(extra="forbid")

    outbound: list[GraphNodeOut]
    inbound: list[GraphNodeOut]


class EmbedStatusOut(BaseModel):
    """Embedding backlog — SPEC-210 deliverable #3's status surface."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    available: bool
    model: str
    dim: int
    total: int
    ready: int
    pending: int
    failed: int
    reason: str


class IndexStatusOut(BaseModel):
    """One vault's index status: the dashboard's "index status" tile.

    ``embed_progress_percent`` and ``embed_summary`` are pre-computed here
    rather than left for the dashboard to derive, so the wording (SPEC-210's
    "searchable now, semantic search catching up — N%") comes from one
    place instead of being re-implemented in TypeScript.
    """

    model_config = ConfigDict(extra="forbid")

    vault: str
    schema_version: int
    notes: int
    observations: int
    relations: int
    unresolved_relations: int
    embeds: EmbedStatusOut
    embed_progress_percent: int
    embed_summary: str

    @classmethod
    def from_status(cls, status: IndexStatus) -> IndexStatusOut:
        embeds = status.embeds
        percent, summary = embed_progress(embeds)
        return cls(
            vault=status.vault,
            schema_version=status.schema_version,
            notes=status.notes,
            observations=status.observations,
            relations=status.relations,
            unresolved_relations=status.unresolved_relations,
            embeds=EmbedStatusOut(**dataclasses.asdict(embeds)),
            embed_progress_percent=percent,
            embed_summary=summary,
        )


def _vault_out(key: str, info: VaultInfo) -> VaultOut:
    return VaultOut(
        key=key,
        purpose=info.purpose,
        path=info.path,
        writable=info.writable,
        note_count=info.note_count,
    )


async def _get_engine(registry: VaultRegistry, vault_key: str) -> VaultEngine:
    try:
        return await registry.get(vault_key)
    except VaultNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def build_dashboard_router(
    registry: VaultRegistry,
    *,
    indexes: dict[str, VaultIndex] | None = None,
    dynamic_gateway: DynamicGateway | None = None,
    curator: CuratorWiring | None = None,
) -> APIRouter:
    """Build the wizard + explorer router, bound to ``registry``.

    Args:
        registry: as before this SPEC.
        indexes: the hub's ``{vault_key: VaultIndex}`` mapping (SPEC-210).
            Given, a vault created here also gets a real
            :class:`~palaia_hub.index.VaultIndex` opened and added to this
            same dict (so ``GET .../index_status`` and the hub's own
            shutdown-time ``index.close()`` loop see it too), and
            ``search_notes`` below runs through it instead of the linear
            engine scan. Omitted, vault creation behaves exactly as before
            this parameter existed — no index, no ``index_status`` route.
        dynamic_gateway: the SPEC-210
            :class:`~palaia_hub.gateway.dynamic.DynamicGateway`. Given, a
            vault created here is also mounted into
            :data:`DEFAULT_GATEWAY_PROFILE` on the running gateway — no hub
            restart needed before an MCP client can reach it. Omitted
            (unchanged default), a wizard-created vault stays
            dashboard/REST-visible only, exactly as documented in this
            module's docstring before this parameter existed.
        curator: the hub's wired-up curator (SPEC-206/301), when
            ``curator.enabled``. Given, a vault created here also joins the
            curator profile's vault set and its guard's tool-action map —
            closing SPEC-206's documented "curator starts curating that
            vault's inbox after the next hub restart" gap (SPEC-301
            deliverable #4). Omitted, behavior is unchanged: the vault is
            still mounted on :data:`DEFAULT_GATEWAY_PROFILE` alone.
    """
    router = APIRouter(tags=["dashboard"])

    @router.post("/api/vaults", response_model=VaultOut)
    async def create_vault(body: CreateVaultRequest) -> VaultOut:
        path = Path(body.path) if body.path else registry.home / "vaults" / body.key
        try:
            engine = await registry.create(body.key, path, purpose=body.purpose)
        except VaultConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if body.template:
            for title, note_body in _TEMPLATE_NOTES:
                await engine.write_note(f"{pl.slugify(title)}.md", body=note_body, title=title)

        index: VaultIndex | None = None
        if indexes is not None:
            index = VaultIndex(engine)
            await index.open()
            indexes[body.key] = index

        if dynamic_gateway is not None:
            service = EngineVaultService(engine, index)
            mount = VaultMountConfig(
                key=body.key,
                name=body.key,
                purpose=body.purpose or "A palaia memory vault.",
            )
            # Curator wiring first: by the time the curator profile becomes
            # reachable with this vault mounted (next), its guard already
            # recognizes the vault's tools — fail-closed in between rather
            # than briefly wide open.
            if curator is not None:
                await curator.add_vault(engine, mount)
            profile_paths = [DEFAULT_GATEWAY_PROFILE]
            if curator is not None:
                profile_paths.append(CURATOR_PROFILE_PATH)
            await dynamic_gateway.add_vault(mount, service, profile_paths=profile_paths)

        return _vault_out(body.key, engine.info())

    @router.get("/api/vaults", response_model=list[VaultOut])
    async def list_vaults() -> list[VaultOut]:
        out: list[VaultOut] = []
        for record in registry.records():
            engine = await registry.get(record.name)
            out.append(_vault_out(record.name, engine.info()))
        return out

    @router.get("/api/vaults/{vault_key}/notes", response_model=list[NoteSummary])
    async def list_notes(vault_key: str, folder: str = "") -> list[NoteSummary]:
        engine = await _get_engine(registry, vault_key)
        return await EngineVaultService(engine).list_notes(folder=folder)

    @router.get("/api/vaults/{vault_key}/search", response_model=list[SearchHit])
    async def search_notes(vault_key: str, q: str = "", limit: int = 10) -> list[SearchHit]:
        engine = await _get_engine(registry, vault_key)
        if not q.strip():
            return []
        index = indexes.get(vault_key) if indexes is not None else None
        return await EngineVaultService(engine, index).search(q, limit=limit)

    @router.get("/api/vaults/{vault_key}/index_status", response_model=IndexStatusOut)
    async def index_status(vault_key: str) -> IndexStatusOut:
        index = indexes.get(vault_key) if indexes is not None else None
        if index is None:
            raise HTTPException(
                status_code=404,
                detail=f"no index open for vault {vault_key!r}",
            )
        return IndexStatusOut.from_status(index.status())

    @router.get("/api/vaults/{vault_key}/review", response_model=ReviewQueueResult)
    async def list_review_queue(vault_key: str) -> ReviewQueueResult:
        engine = await _get_engine(registry, vault_key)
        return await EngineVaultService(engine).review_queue()

    @router.post(
        "/api/vaults/{vault_key}/review/{permalink:path}/decision",
        response_model=ReviewDecideResult,
    )
    async def decide_review(
        vault_key: str, permalink: str, body: ReviewDecisionRequest
    ) -> ReviewDecideResult:
        engine = await _get_engine(registry, vault_key)
        try:
            return await EngineVaultService(engine).review_decide(permalink, body.decision)
        except VaultServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(
        "/api/vaults/{vault_key}/notes/{permalink:path}/history",
        response_model=list[CommitOut],
    )
    async def note_history(vault_key: str, permalink: str, limit: int = 50) -> list[CommitOut]:
        engine = await _get_engine(registry, vault_key)
        try:
            entry = engine.resolve(permalink)
        except (NoteNotFoundError, AmbiguousReferenceError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        commits = await engine.history(entry.path, limit=limit)
        return [CommitOut.from_commit(commit) for commit in commits]

    @router.get(
        "/api/vaults/{vault_key}/notes/{permalink:path}/graph",
        response_model=LocalGraphOut,
    )
    async def note_graph(vault_key: str, permalink: str) -> LocalGraphOut:
        engine = await _get_engine(registry, vault_key)
        return await _local_graph(engine, permalink)

    @router.get("/api/vaults/{vault_key}/notes/{permalink:path}", response_model=NoteRecord)
    async def read_note(vault_key: str, permalink: str) -> NoteRecord:
        engine = await _get_engine(registry, vault_key)
        try:
            return await EngineVaultService(engine).read(permalink)
        except VaultServiceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


async def _local_graph(engine: VaultEngine, permalink: str) -> LocalGraphOut:
    try:
        entry = engine.resolve(permalink)
        note = await engine.read_note(entry.path)
    except (NoteNotFoundError, AmbiguousReferenceError, InvalidPathError) as exc:
        raise HTTPException(
            status_code=404, detail=f"no note matching {permalink!r}"
        ) from exc

    outbound: list[GraphNodeOut] = []
    seen: set[str] = {entry.path}
    for link in iter_links(note.body):
        target = link.target.strip()
        if not target:
            continue
        try:
            target_entry = engine.resolve(target)
        except (NoteNotFoundError, AmbiguousReferenceError):
            continue  # linked before it exists — not an edge yet
        if target_entry.path in seen:
            continue
        seen.add(target_entry.path)
        target_note = await engine.read_note(target_entry.path)
        outbound.append(
            GraphNodeOut(
                permalink=target_entry.permalink or target_entry.path, title=target_note.title
            )
        )

    inbound: list[GraphNodeOut] = []
    seen_in: set[str] = {entry.path}
    for candidate in list(engine.catalog.values()):
        if candidate.path == entry.path:
            continue
        candidate_note = await engine.read_note(candidate.path)
        for link in iter_links(candidate_note.body):
            target = link.target.strip()
            if not target:
                continue
            try:
                target_entry = engine.resolve(target)
            except (NoteNotFoundError, AmbiguousReferenceError):
                continue
            if target_entry.path == entry.path and candidate.path not in seen_in:
                seen_in.add(candidate.path)
                inbound.append(
                    GraphNodeOut(
                        permalink=candidate.permalink or candidate.path,
                        title=candidate_note.title,
                    )
                )
                break

    return LocalGraphOut(outbound=outbound, inbound=inbound)


__all__ = ["build_dashboard_router"]
