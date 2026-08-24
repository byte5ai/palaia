"""Client registration: CIMD first, RFC 7591 DCR as the legacy fallback.

Three ways a client can come to exist, and they are not equal:

1. **CIMD** (:mod:`palaia_hub.oauth.cimd`) — the client's ``client_id`` is an
   https URL; the hub fetches the document, validates it, and caches the row.
   Nothing is "registered" in the RFC 7591 sense, so a reconnect finds the
   same row instead of creating a new one. This is what MCP 2026-07-28
   recommends and what this hub prefers.
2. **DCR** (RFC 7591, ``POST /register``) — deprecated by MCP 2026-07-28 but
   still what several shipping clients do, so it is supported and *fenced*:
   public clients only, PKCE mandatory, no way to ask for
   ``client_credentials``, a hard ceiling on how many such rows may exist,
   and a GC pass that removes the orphans
   (:meth:`palaia_hub.oauth.store.OAuthStore.prune_clients`).
3. **Admin provisioning** (:func:`provision_machine_client`) — the only path
   that produces a confidential client with a secret and a pinned audience.
   MASTERPLAN §5.5: machine identities "are provisioned by the admin — pinned
   to exactly one audience and scope grant, never obtainable through public
   client registration, no refresh tokens." All three of those are enforced
   here and in :mod:`palaia_hub.oauth.service`, not merely documented.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from ..auth.hashing import hash_secret as hash_password
from .cimd import (
    ALLOWED_GRANT_TYPES,
    MAX_CLIENT_NAME_CHARS,
    MAX_REDIRECT_URIS,
    CimdFetcher,
    is_cimd_client_id,
    validate_redirect_uri,
)
from .errors import OAuthError
from .models import ClientRow, ProvisionedMachineClient
from .secrets_util import new_secret
from .store import OAuthStore

logger = logging.getLogger("palaia_hub.oauth.clients")

#: Prefix on a dynamically registered ``client_id``, so a row's provenance is
#: readable at a glance in the dashboard and in logs.
DCR_CLIENT_ID_PREFIX = "dcr_"

#: How many self-registered (DCR) clients may exist at once. A ceiling rather
#: than a rate limit: the GC keeps the steady state small, and this stops a
#: burst of registrations from filling the disk before the GC's next pass.
#: Reaching it is a signal, so it is logged at WARNING.
MAX_DCR_CLIENTS = 500


def register_dcr_client(
    store: OAuthStore, body: Any, *, now: int, allowed_scopes: Sequence[str]
) -> ClientRow:
    """Handle an RFC 7591 registration request; return the created client.

    The response the client gets is assembled by
    :mod:`palaia_hub.oauth.routes` from this row — it never contains a
    ``client_secret``, because a client that registered itself is by
    definition a public client and gets PKCE instead.

    Raises:
        OAuthError: ``invalid_client_metadata``/``invalid_redirect_uri`` for a
            malformed request, or when the DCR ceiling is reached.
    """
    if not isinstance(body, dict):
        raise OAuthError("invalid_client_metadata", "the registration body must be a JSON object.")

    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        raise OAuthError(
            "invalid_client_metadata",
            "'redirect_uris' is required and must list at least one URL.",
        )
    if len(redirect_uris) > MAX_REDIRECT_URIS:
        raise OAuthError(
            "invalid_client_metadata",
            f"a client may declare at most {MAX_REDIRECT_URIS} redirect URIs.",
        )
    validated: list[str] = []
    for uri in redirect_uris:
        if not isinstance(uri, str) or not uri:
            raise OAuthError(
                "invalid_client_metadata", "'redirect_uris' must contain non-empty strings."
            )
        validated.append(validate_redirect_uri(uri))

    grant_types = body.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list):
        raise OAuthError("invalid_client_metadata", "'grant_types' must be a list.")
    unsupported = [g for g in grant_types if g not in ALLOWED_GRANT_TYPES]
    if unsupported:
        raise OAuthError(
            "invalid_client_metadata",
            "dynamic registration may only request the "
            f"{list(ALLOWED_GRANT_TYPES)} grant types; machine-to-machine "
            "credentials are provisioned by the hub's operator, never requested.",
        )

    auth_method = body.get("token_endpoint_auth_method", "none")
    if auth_method != "none":
        raise OAuthError(
            "invalid_client_metadata",
            "'token_endpoint_auth_method' must be 'none': a dynamically "
            "registered client is a public client and authenticates with PKCE. "
            "Ask the hub's operator for a machine client if you need a secret.",
        )

    existing = store.count_clients(source="dcr")
    if existing >= MAX_DCR_CLIENTS:
        logger.warning(
            "refusing dynamic client registration: %d DCR clients already stored "
            "(ceiling %d). The garbage collector prunes orphans; a persistent "
            "ceiling means clients are registering faster than they are used.",
            existing,
            MAX_DCR_CLIENTS,
        )
        raise OAuthError(
            "invalid_client_metadata",
            "this hub is not accepting further dynamic client registrations right "
            "now. Fix: use a client-id metadata document (CIMD), which needs no "
            "registration at all.",
        )

    raw_name = body.get("client_name")
    client_name = (
        raw_name[:MAX_CLIENT_NAME_CHARS] if isinstance(raw_name, str) and raw_name else "unnamed"
    )
    client = ClientRow(
        client_id=f"{DCR_CLIENT_ID_PREFIX}{new_secret()}",
        source="dcr",
        client_name=client_name,
        redirect_uris=tuple(dict.fromkeys(validated)),
        grant_types=tuple(dict.fromkeys(grant_types)),
        scopes=tuple(allowed_scopes),
        created_at=now,
        last_seen_at=now,
    )
    store.put_client(client)
    logger.info(
        "registered client %s via RFC 7591 DCR (name=%r)", client.client_id, client.client_name
    )
    return client


async def resolve_client(
    store: OAuthStore,
    fetcher: CimdFetcher,
    client_id: str,
    *,
    now: int,
    allowed_scopes: Sequence[str],
) -> ClientRow:
    """Return the client behind ``client_id``, registering it from CIMD if new.

    CIMD-first: an https ``client_id`` is resolved by fetching its metadata
    document even when a row already exists, so a client that changed its
    redirect URIs is not stuck with a stale row — the fetch is what makes
    CIMD self-maintaining. If the fetch fails but a row exists, the stored row
    is used (a temporarily unreachable document must not lock out a client
    that already works); if the fetch fails and there is no row, the error
    surfaces.

    Raises:
        OAuthError: ``invalid_client`` for an unknown non-CIMD client id.
    """
    if is_cimd_client_id(client_id):
        cached = store.get_client(client_id)
        try:
            metadata = await fetcher.fetch(client_id)
        except OAuthError:
            if cached is not None:
                logger.info(
                    "client-id metadata document for %s is unreachable; using the "
                    "stored registration",
                    client_id,
                )
                return cached
            raise
        client = ClientRow(
            client_id=client_id,
            source="cimd",
            client_name=str(metadata["client_name"]),
            redirect_uris=tuple(dict.fromkeys(metadata["redirect_uris"])),
            grant_types=tuple(metadata["grant_types"]),
            scopes=tuple(allowed_scopes),
            created_at=cached.created_at if cached is not None else now,
            last_seen_at=now,
        )
        store.put_client(client)
        return client

    registered = store.get_client(client_id)
    if registered is None:
        raise OAuthError(
            "invalid_client",
            "unknown client_id. Fix: register the client (POST /register), or use "
            "an https client-id metadata document URL as the client_id.",
        )
    return registered


def provision_machine_client(
    store: OAuthStore,
    *,
    client_name: str,
    audience: str,
    scopes: Sequence[str],
    now: int,
) -> ProvisionedMachineClient:
    """Create an admin-provisioned machine client. Returns its secret once.

    The secret is 256 bits of CSPRNG output stored as an argon2id hash — the
    same hasher :mod:`palaia_hub.auth.hashing` uses for MVP client tokens,
    reused rather than re-parameterized. argon2 (not the SHA-256 used for the
    package's other opaque secrets) because this one is presented on the
    ``/token`` endpoint by a caller the hub cannot rate-limit as tightly as a
    login form, and its verification cost is paid at most once per short-lived
    access token.

    The audience is pinned here and can never be widened by the client: see
    :meth:`palaia_hub.oauth.service.AuthorizationServer._client_credentials`.
    """
    if not client_name:
        raise OAuthError("invalid_request", "a machine client needs a name.")
    if not scopes:
        raise OAuthError("invalid_scope", "a machine client needs at least one scope.")
    secret = new_secret()
    client = ClientRow(
        client_id=f"machine_{new_secret()}",
        source="admin",
        client_name=client_name[:MAX_CLIENT_NAME_CHARS],
        redirect_uris=(),
        grant_types=("client_credentials",),
        scopes=tuple(scopes),
        created_at=now,
        last_seen_at=now,
        client_secret_hash=hash_password(secret),
        pinned_audience=audience,
        is_machine=True,
    )
    store.put_client(client)
    logger.info(
        "provisioned machine client %s (name=%r, audience=%s)",
        client.client_id,
        client.client_name,
        audience,
    )
    return ProvisionedMachineClient(client=client, client_secret=secret)


__all__ = [
    "DCR_CLIENT_ID_PREFIX",
    "MAX_DCR_CLIENTS",
    "provision_machine_client",
    "register_dcr_client",
    "resolve_client",
]
