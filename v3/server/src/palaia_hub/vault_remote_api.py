"""``/api/backup/vault-remotes`` — push a vault to a git repository (issue #438).

The dashboard's Backups screen configures, runs and removes the push of each
vault into a git repository the owner names (:mod:`palaia_hub.vault_remote`):

* ``GET /api/backup/vault-remotes`` — every vault, with its push if one is
  set up and how the last push went. Never a token, only whether one is
  stored.
* ``PUT /api/backup/vault-remotes/{vault}`` — set or change the repository
  URL, branch, user name and (write-only) token.
* ``DELETE /api/backup/vault-remotes/{vault}`` — stop pushing, delete the token.
* ``POST /api/backup/vault-remotes/{vault}/push`` — push now. 409 while that
  vault is already being pushed.

Same posture as the rest of ``/api/backup`` (:mod:`palaia_hub.backup_api`):
only a signed-in owner reaches it, and on a hub without dashboard sign-in
every route refuses with 403. The token entered here can write to the
owner's repository; handing that form to anyone who can reach the hub would
be the same mistake as handing out the archive.

Mounted only when the hub has both a vault registry and a secret store —
there is nothing to push without the first and nowhere to keep the token
without the second.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .backup_schedule import MANUAL_TRIGGER
from .upstream.secrets import SecretStoreError
from .vault_remote import VaultRemoteBusyError, VaultRemoteError, VaultRemotes

VAULT_REMOTES_PATH = "/api/backup/vault-remotes"
VAULT_REMOTE_PATH = "/api/backup/vault-remotes/{vault}"
VAULT_REMOTE_PUSH_PATH = "/api/backup/vault-remotes/{vault}/push"

UNGATED_VAULT_REMOTES_DETAIL = (
    "Pushing vaults to a git repository is only set up by a signed-in owner, and "
    "this hub has no dashboard sign-in turned on — the access token entered here can "
    "write to your repository. Fix: turn on sign-in (`oauth.enabled: true` and "
    "`oauth.issuer` in config.yaml, then `palaia-hub oauth set-password`)."
)


class VaultRemoteIn(BaseModel):
    """What the Backups screen sends. ``token`` is write-only: it goes to the
    encrypted secret store and is never sent back."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2048)
    branch: str | None = Field(default=None, max_length=200)
    username: str | None = Field(default=None, max_length=100)
    token: str | None = Field(default=None, max_length=4096)


def build_vault_remote_router(remotes: VaultRemotes, *, session_gated: bool = True) -> APIRouter:
    """Build the ``/api/backup/vault-remotes`` router.

    Args:
        remotes: the hub's configured vault pushes.
        session_gated: whether the admin session gate wraps this router.
            ``False`` makes every route refuse with 403 (see the module
            docstring).
    """
    router = APIRouter(tags=["backup"])

    def _gate() -> None:
        if not session_gated:
            raise HTTPException(status_code=403, detail=UNGATED_VAULT_REMOTES_DETAIL)

    def _one(vault: str) -> dict[str, Any]:
        for entry in remotes.describe():
            if entry["vault"] == vault:
                return entry
        raise HTTPException(status_code=404, detail=f"No vault named {vault!r} on this hub.")

    @router.get(VAULT_REMOTES_PATH)
    async def list_vault_remotes() -> dict[str, Any]:
        _gate()
        return {"vaults": remotes.describe()}

    @router.put(VAULT_REMOTE_PATH)
    async def configure_vault_remote(vault: str, body: VaultRemoteIn) -> dict[str, Any]:
        _gate()
        try:
            await run_in_threadpool(
                remotes.configure,
                vault,
                url=body.url,
                branch=body.branch,
                username=body.username,
                token=body.token,
            )
        except (VaultRemoteError, SecretStoreError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _one(vault)

    @router.delete(VAULT_REMOTE_PATH)
    async def remove_vault_remote(vault: str) -> dict[str, Any]:
        _gate()
        if not await run_in_threadpool(remotes.remove, vault):
            raise HTTPException(
                status_code=404, detail=f"Vault {vault!r} is not pushed to a git repository."
            )
        return {"removed": vault}

    @router.post(VAULT_REMOTE_PUSH_PATH)
    async def push_vault(vault: str) -> dict[str, Any]:
        """Push one vault now, on a worker thread (a push is network I/O)."""
        _gate()
        if remotes.get(vault) is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Vault {vault!r} is not pushed to a git repository. Fix: set one up "
                    "on the Backups screen first."
                ),
            )
        try:
            record = await run_in_threadpool(remotes.push, vault, trigger=MANUAL_TRIGGER)
        except VaultRemoteBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except VaultRemoteError as exc:
            # The owner's repository refused, or could not be reached: the
            # request was fine, this hub could not carry it out.
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"vault": vault, **record.to_json()}

    return router


__all__ = [
    "UNGATED_VAULT_REMOTES_DETAIL",
    "VAULT_REMOTES_PATH",
    "VAULT_REMOTE_PATH",
    "VAULT_REMOTE_PUSH_PATH",
    "VaultRemoteIn",
    "build_vault_remote_router",
]
