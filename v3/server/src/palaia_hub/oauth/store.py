"""The authorization server's state: one SQLite file, one connection, one lock.

**Why the locking discipline is spelled out rather than assumed.** The
failure this store is designed against is recorded in MASTERPLAN §5.5: a
single claude.ai connector fans out over web, phone and desktop, so several
*concurrent* refresh requests arrive for the same grant. With per-request
connections and no serialization, two refreshes interleave, both read the
same un-spent row, both rotate it, and one of them ends up holding a token
the other invalidated — which in the mcp-hub prototype showed up as a daily
re-login. So:

* **One connection**, opened ``check_same_thread=False``, plus one
  ``threading.RLock``. Every statement in this module runs while that lock is
  held. This is the same shape (and the same reasoning) as
  :class:`palaia_hub.index.db.IndexDatabase`: SQLite serializes writers
  anyway, and an authorization server is not a contended OLTP database.
* **Every multi-statement mutation is one explicit ``BEGIN IMMEDIATE``
  transaction**, committed or rolled back inside the same ``with self._lock``
  block. ``BEGIN IMMEDIATE`` takes the write lock up front, so two
  concurrent rotations cannot both pass their read phase.
  ``isolation_level=None`` turns off the sqlite3 module's implicit
  transaction handling, which would otherwise open transactions at points
  this module did not choose.
* **The whole read-decide-write of a rotation lives in one method**
  (:meth:`rotate_refresh_token`) rather than being composed by a caller out
  of getters and setters — a caller cannot accidentally split the atomic
  step in two.
* **WAL**, so the dashboard reading client rows never blocks a token
  request.

**What is persisted.** Clients, grants, and *digests* of authorization codes,
refresh tokens and login session ids (:mod:`palaia_hub.oauth.secrets_util`
explains which hash and why). Access tokens are never persisted at all —
they are self-contained JWTs with a short TTL, which is what makes the
resource side verifiable without a round-trip back here.

The database file and its journal are held at ``0600`` inside the ``0700``
``<home>/oauth/`` directory, re-enforced on every open.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from ..security.files import harden_sqlite_database
from .errors import OAuthError
from .keys import oauth_dir
from .models import (
    ClientRow,
    ClientSource,
    CodeRow,
    GrantRow,
    IdpStateRow,
    PruneReport,
    RefreshRow,
    RotationOutcome,
)
from .secrets_util import hash_secret, new_secret

logger = logging.getLogger("palaia_hub.oauth.store")

DATABASE_FILE = "oauth.sqlite3"

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    client_id          TEXT PRIMARY KEY,
    source             TEXT NOT NULL,
    client_name        TEXT NOT NULL,
    redirect_uris      TEXT NOT NULL,
    grant_types        TEXT NOT NULL,
    scopes             TEXT NOT NULL,
    client_secret_hash TEXT,
    pinned_audience    TEXT,
    is_machine         INTEGER NOT NULL DEFAULT 0,
    created_at         INTEGER NOT NULL,
    last_seen_at       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS grants (
    grant_id   TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    subject    TEXT NOT NULL,
    audience   TEXT NOT NULL,
    scopes     TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS grants_client ON grants(client_id);

CREATE TABLE IF NOT EXISTS codes (
    code_hash      TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    redirect_uri   TEXT NOT NULL,
    code_challenge TEXT NOT NULL,
    audience       TEXT NOT NULL,
    subject        TEXT NOT NULL,
    scopes         TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    expires_at     INTEGER NOT NULL,
    consumed_at    INTEGER,
    grant_id       TEXT
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash     TEXT PRIMARY KEY,
    grant_id       TEXT NOT NULL,
    client_id      TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    expires_at     INTEGER NOT NULL,
    rotated_at     INTEGER,
    successor_hash TEXT,
    grace_until    INTEGER,
    revoked_at     INTEGER
);
CREATE INDEX IF NOT EXISTS refresh_grant ON refresh_tokens(grant_id);
CREATE INDEX IF NOT EXISTS refresh_client ON refresh_tokens(client_id);

CREATE TABLE IF NOT EXISTS owner_account (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS login_sessions (
    session_hash TEXT PRIMARY KEY,
    username     TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS idp_states (
    state_hash TEXT PRIMARY KEY,
    provider   TEXT NOT NULL,
    next_url   TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
"""

#: meta key holding the epoch second of the last registered-client GC pass.
META_LAST_CLIENT_GC = "clients_gc_last_run"
META_SCHEMA_VERSION = "schema_version"


def _dump(values: Sequence[str]) -> str:
    return json.dumps(list(values))


def _load(raw: str) -> tuple[str, ...]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list):  # pragma: no cover - we wrote it
        return ()
    return tuple(str(item) for item in parsed)


class OAuthStore:
    """Every persistent piece of authorization-server state.

    Args:
        home: the hub home directory; the database lives at
            ``<home>/oauth/oauth.sqlite3``.
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home).expanduser()
        self.path = oauth_dir(self.home) / DATABASE_FILE
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------- lifecycle

    def open(self) -> None:
        """Open the database, creating the schema on first use."""
        with self._lock:
            if self._conn is not None:
                return
            # isolation_level=None: this module owns its transaction
            # boundaries explicitly (see the module docstring).
            conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.executescript(SCHEMA_SQL)
            existing = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (META_SCHEMA_VERSION,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES (?, ?)",
                    (META_SCHEMA_VERSION, str(SCHEMA_VERSION)),
                )
            elif str(existing["value"]) != str(SCHEMA_VERSION):
                conn.close()
                raise OAuthError(
                    "server_error",
                    f"{self.path} was written by schema version "
                    f"{existing['value']!r} but this hub speaks {SCHEMA_VERSION}. "
                    f"Fix: move the file aside (every client re-authorizes once).",
                )
            self._conn = conn
        # The journal/WAL siblings appear on first write; narrowing all three
        # here and again on close covers both.
        self._enforce_modes()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        self._enforce_modes()

    def _enforce_modes(self) -> None:
        harden_sqlite_database(self.path, with_parent=True)

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("OAuth store is not open — call open() first")
        return self._conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """Hold the lock and one ``BEGIN IMMEDIATE`` transaction.

        ``BEGIN IMMEDIATE`` (rather than SQLite's default deferred begin)
        acquires the write lock before the first read, so a concurrent writer
        cannot slip between this transaction's read and write phases — the
        property the refresh fan-out depends on.
        """
        with self._lock:
            conn = self._db
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            else:
                conn.execute("COMMIT")

    # ------------------------------------------------------------------ meta

    def meta_get(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def meta_set(self, key: str, value: str) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # --------------------------------------------------------------- clients

    def put_client(self, client: ClientRow) -> None:
        """Insert or replace a client row wholesale."""
        with self._write() as conn:
            conn.execute(
                "INSERT INTO clients(client_id, source, client_name, redirect_uris, "
                "grant_types, scopes, client_secret_hash, pinned_audience, is_machine, "
                "created_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(client_id) DO UPDATE SET "
                "  source = excluded.source,"
                "  client_name = excluded.client_name,"
                "  redirect_uris = excluded.redirect_uris,"
                "  grant_types = excluded.grant_types,"
                "  scopes = excluded.scopes,"
                "  last_seen_at = excluded.last_seen_at",
                (
                    client.client_id,
                    client.source,
                    client.client_name,
                    _dump(client.redirect_uris),
                    _dump(client.grant_types),
                    _dump(client.scopes),
                    client.client_secret_hash,
                    client.pinned_audience,
                    int(client.is_machine),
                    client.created_at,
                    client.last_seen_at,
                ),
            )

    def get_client(self, client_id: str) -> ClientRow | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        return None if row is None else _client_from_row(row)

    def list_clients(self) -> list[ClientRow]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM clients ORDER BY created_at").fetchall()
        return [_client_from_row(row) for row in rows]

    def count_clients(self, *, source: ClientSource | None = None) -> int:
        with self._lock:
            if source is None:
                row = self._db.execute("SELECT COUNT(*) AS n FROM clients").fetchone()
            else:
                row = self._db.execute(
                    "SELECT COUNT(*) AS n FROM clients WHERE source = ?", (source,)
                ).fetchone()
        return int(row["n"])

    def touch_client(self, client_id: str, now: int) -> None:
        """Record that ``client_id`` was seen — the input the GC ages on."""
        with self._write() as conn:
            conn.execute(
                "UPDATE clients SET last_seen_at = ? WHERE client_id = ?", (now, client_id)
            )

    def delete_client(self, client_id: str) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM clients WHERE client_id = ?", (client_id,))

    # ---------------------------------------------------------------- grants

    def get_grant(self, grant_id: str) -> GrantRow | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM grants WHERE grant_id = ?", (grant_id,)
            ).fetchone()
        return None if row is None else _grant_from_row(row)

    def revoke_grant(self, grant_id: str, now: int) -> None:
        """Revoke a grant and every refresh token derived from it."""
        with self._write() as conn:
            conn.execute(
                "UPDATE grants SET revoked_at = ? WHERE grant_id = ? AND revoked_at IS NULL",
                (now, grant_id),
            )
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = ? "
                "WHERE grant_id = ? AND revoked_at IS NULL",
                (now, grant_id),
            )

    def count_live_refresh_tokens(self, client_id: str, now: int) -> int:
        """Refresh tokens for ``client_id`` that could still be exchanged."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM refresh_tokens r "
                "JOIN grants g ON g.grant_id = r.grant_id "
                "WHERE r.client_id = ? AND r.revoked_at IS NULL AND r.expires_at > ? "
                "AND g.revoked_at IS NULL",
                (client_id, now),
            ).fetchone()
        return int(row["n"])

    # ----------------------------------------------------------------- codes

    def create_code(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        audience: str,
        subject: str,
        scopes: Sequence[str],
        now: int,
        ttl: int,
    ) -> str:
        """Mint an authorization code; returns the plaintext (stored hashed)."""
        code = new_secret()
        with self._write() as conn:
            conn.execute(
                "INSERT INTO codes(code_hash, client_id, redirect_uri, code_challenge, "
                "audience, subject, scopes, created_at, expires_at, consumed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    hash_secret(code),
                    client_id,
                    redirect_uri,
                    code_challenge,
                    audience,
                    subject,
                    _dump(scopes),
                    now,
                    now + ttl,
                ),
            )
            # Opportunistic housekeeping: codes are single-use and live for a
            # minute, so anything long past its expiry is dead weight.
            conn.execute("DELETE FROM codes WHERE expires_at < ?", (now - 3600,))
        return code

    def exchange_code(self, code: str, now: int) -> tuple[CodeRow, GrantRow]:
        """Atomically spend an authorization code and create its grant.

        Spending the code and creating the grant it authorizes are one step
        on purpose: split into two transactions, a crash between them would
        leave either a burnt code with no grant (the client re-authorizes,
        annoying but safe) or — far worse — a grant nobody can attribute to a
        code, which is what makes replay detection unreliable. Together, the
        code row also records *which* grant it produced, so a replay revokes
        exactly that grant and nothing else.

        Raises:
            OAuthError: ``invalid_grant`` for unknown, expired, or
                already-spent codes. A code presented twice additionally
                **revokes the grant it produced** (RFC 9700 §4.13): unlike a
                refresh token, an authorization code has exactly one
                legitimate use by exactly one client at one moment, so a
                second presentation is evidence of interception rather than
                of one connector fanning out over three devices — which is
                why codes get textbook replay handling and refresh tokens get
                a grace window.
        """
        result = self._exchange_code_txn(code, now)
        if result is None:
            # Includes the replay case, whose revocation the transaction has
            # already committed — a rejection raised from *inside* ``_write()``
            # rolls back, which is right for a read-only rejection and would
            # be exactly wrong for that one.
            raise OAuthError("invalid_grant", "the authorization code is not valid.")
        return result

    def _exchange_code_txn(self, code: str, now: int) -> tuple[CodeRow, GrantRow] | None:
        """One transaction; ``None`` means "reject" (see :meth:`exchange_code`)."""
        code_hash = hash_secret(code)
        with self._write() as conn:
            row = conn.execute("SELECT * FROM codes WHERE code_hash = ?", (code_hash,)).fetchone()
            if row is None:
                return None
            if row["consumed_at"] is not None:
                grant_id = row["grant_id"]
                if grant_id is not None:
                    conn.execute(
                        "UPDATE grants SET revoked_at = ? "
                        "WHERE grant_id = ? AND revoked_at IS NULL",
                        (now, grant_id),
                    )
                    conn.execute(
                        "UPDATE refresh_tokens SET revoked_at = ? "
                        "WHERE grant_id = ? AND revoked_at IS NULL",
                        (now, grant_id),
                    )
                logger.warning(
                    "authorization code replayed for client %s; revoked its grant",
                    row["client_id"],
                )
                return None
            if int(row["expires_at"]) <= now:
                return None
            code_row = _code_from_row(row)
            grant = GrantRow(
                grant_id=new_secret(),
                client_id=code_row.client_id,
                subject=code_row.subject,
                audience=code_row.audience,
                scopes=code_row.scopes,
                created_at=now,
            )
            conn.execute(
                "INSERT INTO grants(grant_id, client_id, subject, audience, scopes, "
                "created_at, revoked_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    grant.grant_id,
                    grant.client_id,
                    grant.subject,
                    grant.audience,
                    _dump(grant.scopes),
                    grant.created_at,
                ),
            )
            conn.execute(
                "UPDATE codes SET consumed_at = ?, grant_id = ? WHERE code_hash = ?",
                (now, grant.grant_id, code_hash),
            )
            conn.execute(
                "UPDATE clients SET last_seen_at = ? WHERE client_id = ?",
                (now, code_row.client_id),
            )
            return code_row, grant

    # -------------------------------------------------------- refresh tokens

    def issue_refresh_token(self, *, grant: GrantRow, now: int, ttl: int) -> tuple[str, int]:
        """Mint the first refresh token of a grant. Returns (plaintext, expiry)."""
        token = new_secret()
        expires_at = now + ttl
        with self._write() as conn:
            conn.execute(
                "INSERT INTO refresh_tokens(token_hash, grant_id, client_id, created_at, "
                "expires_at) VALUES (?, ?, ?, ?, ?)",
                (hash_secret(token), grant.grant_id, grant.client_id, now, expires_at),
            )
        return token, expires_at

    def rotate_refresh_token(
        self, presented: str, *, now: int, ttl: int, grace_window: int
    ) -> RotationOutcome:
        """Exchange a refresh token for a successor, with a grace window.

        This is the method MASTERPLAN §5.5's "grace-windowed refresh rotation
        instead of strict single-use" names, and the whole read-decide-write
        runs in one ``BEGIN IMMEDIATE`` transaction so concurrent callers
        serialize rather than interleave.

        Behaviour:

        * A live, un-spent token is spent: a successor is minted, and the
          presented token is marked ``rotated_at = now``, pinned to that
          successor, and given ``grace_until = now + grace_window``.
        * The **same token presented again inside its grace window** is
          accepted: another successor is minted and returned. This is the
          point of the whole design — claude.ai fans one connector out over
          web, phone and desktop, all three may present the same stored
          refresh token within seconds, and strict single-use answers two of
          them with ``invalid_grant``, tearing the grant down and forcing a
          re-login (the observed mcp-hub incident). ``rotated_at`` and
          ``grace_until`` are set with ``COALESCE`` so they keep their
          *first* values: a replay cannot extend its own window.
        * **After the grace window the presented token is dead** —
          ``invalid_grant``, and deliberately *without* revoking the grant
          family. Family revocation is the textbook reuse-detection response
          (RFC 9700 §4.14.2), but with a credential a vendor cloud
          intentionally shares across three surfaces it re-creates the very
          re-login loop this design exists to remove; the exposure is instead
          bounded by the short refresh TTL and the revocation endpoint. The
          event is logged at WARNING so an operator can act on it.

        Returns:
            A :class:`~palaia_hub.oauth.models.RotationOutcome`.

        Raises:
            OAuthError: ``invalid_grant`` — one code for every rejection
                reason, so a client learns nothing about *why*.
        """
        presented_hash = hash_secret(presented)
        invalid = OAuthError("invalid_grant", "the refresh token is not valid.")
        with self._write() as conn:
            row = conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (presented_hash,)
            ).fetchone()
            if row is None:
                raise invalid
            refresh = _refresh_from_row(row)
            if refresh.revoked_at is not None or refresh.expires_at <= now:
                raise invalid
            grant_row = conn.execute(
                "SELECT * FROM grants WHERE grant_id = ?", (refresh.grant_id,)
            ).fetchone()
            if grant_row is None:
                raise invalid
            grant = _grant_from_row(grant_row)
            if grant.revoked_at is not None:
                raise invalid

            replayed = refresh.rotated_at is not None
            if replayed:
                within_grace = refresh.grace_until is not None and now <= refresh.grace_until
                if not within_grace:
                    logger.warning(
                        "spent refresh token replayed past its grace window "
                        "(client=%s grant=%s); rejected",
                        refresh.client_id,
                        refresh.grant_id,
                    )
                    raise invalid

            successor = new_secret()
            successor_hash = hash_secret(successor)
            expires_at = now + ttl
            conn.execute(
                "INSERT INTO refresh_tokens(token_hash, grant_id, client_id, created_at, "
                "expires_at) VALUES (?, ?, ?, ?, ?)",
                (successor_hash, grant.grant_id, refresh.client_id, now, expires_at),
            )
            conn.execute(
                "UPDATE refresh_tokens SET "
                "  rotated_at = COALESCE(rotated_at, ?),"
                "  grace_until = COALESCE(grace_until, ?),"
                "  successor_hash = ? "
                "WHERE token_hash = ?",
                (now, now + grace_window, successor_hash, presented_hash),
            )
            # Housekeeping inside the same transaction: a token that is both
            # spent and past its grace window can never be exchanged again,
            # and neither can an expired one.
            conn.execute(
                "DELETE FROM refresh_tokens WHERE grant_id = ? AND token_hash != ? "
                "AND ((rotated_at IS NOT NULL AND grace_until < ?) OR expires_at < ?)",
                (grant.grant_id, presented_hash, now, now),
            )
            conn.execute(
                "UPDATE clients SET last_seen_at = ? WHERE client_id = ?",
                (now, refresh.client_id),
            )
            return RotationOutcome(
                grant=grant,
                refresh_token=successor,
                refresh_expires_at=expires_at,
                replayed=replayed,
            )

    def revoke_refresh_token(self, presented: str, now: int) -> bool:
        """Revoke a refresh token and its grant. Returns whether it existed.

        RFC 7009 §2.1 asks that revoking a refresh token also invalidate the
        access tokens issued from it. Access tokens here are self-contained
        JWTs, so they cannot be withdrawn individually — revoking the grant
        stops every future exchange, and the outstanding access tokens expire
        within their (short) TTL. That trade is the price of local,
        round-trip-free verification at the resource, and it is why the
        access-token TTL is minutes rather than hours.
        """
        token_hash = hash_secret(presented)
        with self._write() as conn:
            row = conn.execute(
                "SELECT grant_id FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
            ).fetchone()
            if row is None:
                return False
            grant_id = str(row["grant_id"])
            conn.execute(
                "UPDATE grants SET revoked_at = ? WHERE grant_id = ? AND revoked_at IS NULL",
                (now, grant_id),
            )
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = ? "
                "WHERE grant_id = ? AND revoked_at IS NULL",
                (now, grant_id),
            )
        return True

    def get_refresh_token(self, presented: str) -> RefreshRow | None:
        """Read a refresh token's row by its plaintext (tests and diagnostics)."""
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM refresh_tokens WHERE token_hash = ?", (hash_secret(presented),)
            ).fetchone()
        return None if row is None else _refresh_from_row(row)

    # ---------------------------------------------------- registered-client GC

    def prune_clients(
        self, *, now: int, ttl_seconds: int, throttle_seconds: int, force: bool = False
    ) -> PruneReport:
        """Delete orphaned registered clients, at most once per throttle window.

        MASTERPLAN §5.5: "registered-client garbage collection — every
        reconnect registers a fresh client and nothing cleans them up unless
        you do." A client is pruned only when **all** of these hold:

        * it registered itself (``source`` is ``cimd`` or ``dcr``) — an
          admin-provisioned client is never touched;
        * it is not a machine identity — those are pinned, secret-bearing,
          and never re-registerable, so pruning one would silently break a
          job with no way for it to recover;
        * it holds no refresh token that could still be exchanged;
        * it has not been seen for ``ttl_seconds``.

        Throttled through the ``clients_gc_last_run`` meta key so calling
        this on every token request (which is what happens) costs one indexed
        read almost every time.
        """
        last_run = self.meta_get(META_LAST_CLIENT_GC)
        if not force and last_run is not None and now - int(last_run) < throttle_seconds:
            return PruneReport(ran=False)

        cutoff = now - ttl_seconds
        pruned: list[str] = []
        with self._write() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (META_LAST_CLIENT_GC, str(now)),
            )
            candidates = conn.execute(
                "SELECT client_id FROM clients "
                "WHERE is_machine = 0 AND source IN ('cimd', 'dcr') AND last_seen_at < ? "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM refresh_tokens r JOIN grants g ON g.grant_id = r.grant_id"
                "  WHERE r.client_id = clients.client_id AND r.revoked_at IS NULL"
                "        AND r.expires_at > ? AND g.revoked_at IS NULL"
                ")",
                (cutoff, now),
            ).fetchall()
            for row in candidates:
                client_id = str(row["client_id"])
                conn.execute("DELETE FROM clients WHERE client_id = ?", (client_id,))
                conn.execute("DELETE FROM grants WHERE client_id = ?", (client_id,))
                conn.execute("DELETE FROM refresh_tokens WHERE client_id = ?", (client_id,))
                pruned.append(client_id)
            machines = conn.execute(
                "SELECT COUNT(*) AS n FROM clients WHERE is_machine = 1"
            ).fetchone()
            remaining = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()
        if pruned:
            logger.info("pruned %d orphaned registered client(s)", len(pruned))
        return PruneReport(
            ran=True,
            pruned=pruned,
            kept_machine=int(machines["n"]),
            kept_active=int(remaining["n"]) - int(machines["n"]),
        )

    # ---------------------------------------------------------- owner account

    def set_owner(self, username: str, password_hash: str, now: int) -> None:
        """Create or replace the single local owner account.

        One account by construction: the table is emptied first, so
        ``/login`` can never grow a second door (MASTERPLAN §5.5's "one door
        only" rule, whose IdP half is SPEC-204's).
        """
        with self._write() as conn:
            conn.execute("DELETE FROM owner_account")
            conn.execute("DELETE FROM login_sessions")
            conn.execute(
                "INSERT INTO owner_account(username, password_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (username, password_hash, now, now),
            )

    def get_owner(self) -> tuple[str, str] | None:
        """``(username, password_hash)`` of the owner account, if one exists."""
        with self._lock:
            row = self._db.execute(
                "SELECT username, password_hash FROM owner_account LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return str(row["username"]), str(row["password_hash"])

    def create_login_session(self, username: str, *, now: int, ttl: int) -> tuple[str, int]:
        """Mint a login session id (returned plaintext, stored hashed)."""
        session = new_secret()
        expires_at = now + ttl
        with self._write() as conn:
            conn.execute("DELETE FROM login_sessions WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO login_sessions(session_hash, username, created_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (hash_secret(session), username, now, expires_at),
            )
        return session, expires_at

    def get_login_session(self, session: str, now: int) -> str | None:
        """The username behind a live session id, or ``None``."""
        with self._lock:
            row = self._db.execute(
                "SELECT username, expires_at FROM login_sessions WHERE session_hash = ?",
                (hash_secret(session),),
            ).fetchone()
        if row is None or int(row["expires_at"]) <= now:
            return None
        return str(row["username"])

    def delete_login_session(self, session: str) -> None:
        with self._write() as conn:
            conn.execute(
                "DELETE FROM login_sessions WHERE session_hash = ?", (hash_secret(session),)
            )

    # --------------------------------------------------------------- idp (204)

    def create_idp_state(self, *, provider: str, next_url: str, now: int, ttl: int) -> str:
        """Mint a fresh single-use sign-in ticket (returned plaintext, stored hashed).

        ``next_url`` is the ``/oauth/authorize`` continuation the browser
        started from — held here rather than round-tripped through the IdP,
        per SPEC-204's "ticket never in the URL" rule.
        """
        state = new_secret()
        expires_at = now + ttl
        with self._write() as conn:
            conn.execute("DELETE FROM idp_states WHERE expires_at < ?", (now,))
            conn.execute(
                "INSERT INTO idp_states(state_hash, provider, next_url, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (hash_secret(state), provider, next_url, now, expires_at),
            )
        return state

    def consume_idp_state(self, state: str, *, now: int) -> IdpStateRow | None:
        """Fetch-and-delete the ticket matching ``state``, or ``None``.

        Deleting on every lookup — whether the ticket is found live, found
        expired, or not found at all — is what makes a ticket single-use: a
        second presentation of the same ``state`` (a replay, or the browser's
        back button) always misses, because the row is already gone.
        """
        state_hash = hash_secret(state)
        with self._write() as conn:
            row = conn.execute(
                "SELECT provider, next_url, expires_at FROM idp_states WHERE state_hash = ?",
                (state_hash,),
            ).fetchone()
            conn.execute("DELETE FROM idp_states WHERE state_hash = ?", (state_hash,))
        if row is None or int(row["expires_at"]) <= now:
            return None
        return IdpStateRow(provider=str(row["provider"]), next_url=str(row["next_url"]))


# ------------------------------------------------------------- row adapters


def _client_from_row(row: sqlite3.Row) -> ClientRow:
    source = str(row["source"])
    if source not in ("cimd", "dcr", "admin"):  # pragma: no cover - we wrote it
        source = "dcr"
    return ClientRow(
        client_id=str(row["client_id"]),
        source=source,  # type: ignore[arg-type]
        client_name=str(row["client_name"]),
        redirect_uris=_load(str(row["redirect_uris"])),
        grant_types=_load(str(row["grant_types"])),
        scopes=_load(str(row["scopes"])),
        created_at=int(row["created_at"]),
        last_seen_at=int(row["last_seen_at"]),
        client_secret_hash=(
            None if row["client_secret_hash"] is None else str(row["client_secret_hash"])
        ),
        pinned_audience=(
            None if row["pinned_audience"] is None else str(row["pinned_audience"])
        ),
        is_machine=bool(row["is_machine"]),
    )


def _grant_from_row(row: sqlite3.Row) -> GrantRow:
    return GrantRow(
        grant_id=str(row["grant_id"]),
        client_id=str(row["client_id"]),
        subject=str(row["subject"]),
        audience=str(row["audience"]),
        scopes=_load(str(row["scopes"])),
        created_at=int(row["created_at"]),
        revoked_at=None if row["revoked_at"] is None else int(row["revoked_at"]),
    )


def _code_from_row(row: sqlite3.Row) -> CodeRow:
    return CodeRow(
        code_hash=str(row["code_hash"]),
        client_id=str(row["client_id"]),
        redirect_uri=str(row["redirect_uri"]),
        code_challenge=str(row["code_challenge"]),
        audience=str(row["audience"]),
        subject=str(row["subject"]),
        scopes=_load(str(row["scopes"])),
        created_at=int(row["created_at"]),
        expires_at=int(row["expires_at"]),
        consumed_at=None if row["consumed_at"] is None else int(row["consumed_at"]),
    )


def _refresh_from_row(row: sqlite3.Row) -> RefreshRow:
    return RefreshRow(
        token_hash=str(row["token_hash"]),
        grant_id=str(row["grant_id"]),
        client_id=str(row["client_id"]),
        created_at=int(row["created_at"]),
        expires_at=int(row["expires_at"]),
        rotated_at=None if row["rotated_at"] is None else int(row["rotated_at"]),
        successor_hash=(
            None if row["successor_hash"] is None else str(row["successor_hash"])
        ),
        grace_until=None if row["grace_until"] is None else int(row["grace_until"]),
        revoked_at=None if row["revoked_at"] is None else int(row["revoked_at"]),
    )


__all__ = [
    "DATABASE_FILE",
    "META_LAST_CLIENT_GC",
    "SCHEMA_VERSION",
    "OAuthStore",
]
