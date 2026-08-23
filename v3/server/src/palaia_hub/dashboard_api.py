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

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from .gateway.vault_protocol import NoteRecord, NoteSummary, SearchHit, VaultServiceError
from .gateway.wiring import EngineVaultService
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


def build_dashboard_router(registry: VaultRegistry) -> APIRouter:
    """Build the wizard + explorer router, bound to ``registry``."""
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
        return await EngineVaultService(engine).search(q, limit=limit)

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
