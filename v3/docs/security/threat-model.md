# palaia v3 — Threat model (as built)

> Written for SPEC-502, the internal hardening pass before 3.0. Its companion
> is [external-review-brief.md](external-review-brief.md), which is what a
> hired reviewer starts from; this document is what they check.
>
> **House rule for this file: every mitigation below describes what the code
> does today, and names the module that does it and the test that proves it.**
> Nothing here is aspirational. If a control is missing, it is written down as
> missing, in [§8 Accepted risks and open gaps](#8-accepted-risks-and-open-gaps).
>
> `server/tests/security/test_threat_model_coverage.py` fails the build when a
> router, an MCP mount or a tool family exists in the code and not in this
> document. That is deliberate: a doc that can rot is a doc that will.

---

## 1. What is worth stealing

| Asset | Where it lives | Why an attacker wants it |
|---|---|---|
| **Vault contents** | Plain Markdown under the vault root, plus the derived index (`.palaia/index.sqlite3`) | The point of the product: everything the user's AI assistants know about their work, their people and their decisions |
| **Client tokens** (`plt_…`) | `<home>/tokens.yaml`, argon2id-hashed | Full MCP access to the vaults in the token's profile |
| **OAuth grants, codes and login sessions** | `<home>/oauth/oauth.sqlite3` | A live session is the admin dashboard; a refresh grant is a long-lived MCP client |
| **The token signing key** | `<home>/oauth/signing-key.pem` (ES256 private key) | Mint access tokens for any profile, forever |
| **Upstream credentials** | `<home>/secrets.sqlite3`, encrypted under `<home>/secrets.key` | The user's API keys for *other* services connected through the gateway |
| **Identity-provider client secret** | `config.yaml`, plain text | Impersonate the hub to the user's identity provider |
| **Session-directory secrets** | `<home>/directory.db`, hashed | Speak as another agent: send messages, claim work |
| **Messenger envelopes** | `<home>/messenger.db`, plain text bodies | What the user's agents said to each other |
| **Stash entries** | `<home>/stash.db` | Hand-off payloads between agents — often the most recent, most specific working context |
| **The owner password hash** | `<home>/oauth/oauth.sqlite3`, argon2id | Offline cracking → the whole hub |
| **A downloaded backup archive** | Wherever the owner saved it after `GET /api/backup` (SPEC-604) — outside the hub's control from that point on | Everything in every row above, in one file. Restoring it onto another host impersonates this hub completely |

The first two rows are the reason the product exists; the rest are the doors
to them.

---

## 2. Trust boundaries

```
                    ┌────────────────────── the internet / the LAN ──────────────────────┐
                    │                                                                     │
   AI client  ──────┼─▶  /mcp/*        (bearer or OAuth access token, per profile)        │
   browser    ──────┼─▶  /oauth/*      (no credential yet — this is where one is minted)  │
   browser    ──────┼─▶  /api/*        (owner session cookie + CSRF token)                │
   browser    ──────┼─▶  /             (the dashboard shell: markup only, no data)        │
                    └─────────────────────────────────────────────────────────────────────┘
                                                   │
                                                   ▼
                                    ┌──────────── the hub process ───────────┐
                                    │  gateway  ·  REST  ·  authorization    │
                                    └────────────────────────────────────────┘
                                       │              │               │
                     ┌─────────────────┘              │               └──────────────────┐
                     ▼                                ▼                                  ▼
             the vault on disk               upstream MCP servers                 the curator
          (files the user also edits)      (someone else's process,           (a model, reading and
                                            local container or remote)         proposing vault edits)
```

Six boundaries, and what each one is:

| # | Boundary | Who is on the far side | What crosses it |
|---|---|---|---|
| B1 | **MCP surface** (`/mcp` and its siblings) | Any AI client the user connected | Tool calls with arbitrary arguments; tool results with vault content |
| B2 | **Admin surface** (`/api/*`, the dashboard) | A browser, claimed to be the owner's | Every configuration and administrative action |
| B3 | **Authorization surface** (`/oauth/*`, `/.well-known/*`) | An unauthenticated browser or client | Credentials are minted here |
| B4 | **Upstreams** | Someone else's MCP server, reached over http or spawned as a `stdio` child | The hub's own credentials go out; that server's tool results come back |
| B5 | **Marketplace installs** | A container image from a registry | Code that runs on the user's machine |
| B6 | **The curator** | A model with a narrowed tool profile | Vault content out, proposed vault edits back in |

The **modes table** (MASTERPLAN §5.5) decides how much of B1–B3 is reachable
from where. It is the single most load-bearing control in this document:

| Mode | Bind | MCP surface | Dashboard / `/api/*` | Sign-in required |
|---|---|---|---|---|
| `locked` | private address, enforced at config load | LAN only | LAN only | Off by default, opt-in |
| `cloud` | private address, enforced at config load; a tunnel forwards `/mcp`, `/oauth`, `/.well-known` only | public via the tunnel | private network only | On by default |
| `open` | any | public | public | **Mandatory, and the config is refused without a way to sign in** |

*Enforced by* `server/src/palaia_hub/config.py` (private-bind rule, and the
`open`-mode refusal), `server/src/palaia_hub/modes/tunnel.py` (per-mode path
scoping). *Proven by* `server/tests/modes/test_policy.py`,
`server/tests/modes/test_open_mode.py`, `server/tests/test_admin_session.py`.

---

## 3. Who is attacking

| Profile | Reaches | Realistic goal |
|---|---|---|
| **A1 — the internet at large** | Whatever the mode exposes | Credential stuffing, scanning, spraying the OAuth endpoints |
| **A2 — another device on the LAN** | Everything, in `locked` mode | Read the vault of a hub that assumed the LAN was safe |
| **A3 — another local account** on the same machine | The filesystem | Read `secrets.key`, the signing key, the databases |
| **A4 — a connected AI client** with a valid token | Its profile's tools | Reach a vault it was not scoped to; escalate through a tool argument |
| **A5 — a hostile upstream** the user installed | Tool results the hub relays | Prompt-inject the user's assistant; exfiltrate through a tool result |
| **A6 — a hostile note** (content, not a person) | The parser, the index, every renderer | Crash the parser; script injection in a renderer; prompt injection in a recall result |
| **A7 — a web page the owner visits** while signed in | The owner's browser | Cross-site request forgery against `/api/*` and `/oauth/logout` |

---

## 4. B1 — the MCP surface

**What is mounted.** One catch-all mount (`/mcp`, rebuilt in place as
profiles change) plus five hub-wide tool families with their own mount
paths: `/mcp/stash`, `/mcp/directory`, `/mcp/messenger`, `/mcp/hub`,
`/mcp/market`, `/mcp/team`. Their tool families are
`memory_tools`, `stash_tools`, `directory_tools` and `messenger_tools`
under `server/src/palaia_hub/gateway/`, plus the MCP Apps in
`server/src/palaia_hub/gateway/apps/`.

| Threat | Mitigation as built | Where |
|---|---|---|
| Unauthenticated tool call | Every mounted profile carries a verifier; the hub **refuses to start** an MCP endpoint with auth off in `cloud`/`open` | `server/src/palaia_hub/auth/policy.py`, `server/tests/auth/test_app_auth_policy.py` |
| A token reaching a vault it was not scoped to | Per-token, per-profile scopes checked inside the gateway, not at the edge | `server/src/palaia_hub/auth/scopes.py`, `server/tests/auth/test_scopes.py` |
| A stolen token file | Tokens are argon2id-hashed at rest; the plaintext is shown once at creation and never logged | `server/src/palaia_hub/auth/store.py`, `server/tests/test_logging_redaction.py` |
| A browser session used as MCP auth | The admin gate deliberately never looks at `/mcp/*`; MCP clients authenticate with their own tokens | `server/src/palaia_hub/admin_session.py`, `server/tests/test_admin_session.py` |
| Tool arguments reflected into results | Reflection reaches only the caller that supplied it; every renderer downstream escapes, and credential-shaped text is masked before it can be logged | `server/tests/security/test_injection_surfaces.py` |
| An MCP App page rendering hostile content | Each app escapes what it inserts, and every page carries its own restrictive `<meta>` policy | `server/src/palaia_hub/gateway/apps/shell.py`, `server/tests/gateway/test_apps_shell.py` |

**Not mitigated here:** prompt injection through tool *results* (A5, A6).
See [§8](#8-accepted-risks-and-open-gaps).

---

## 5. B2 — the admin surface

**What is mounted.** Every REST router the hub can serve:

| Route group | What it controls | Notes |
|---|---|---|
| `/api/health` | liveness | sign-in-free by design |
| `/api/info` | version, mode, how to sign in | sign-in-free by design; carries no secret |
| `/api/session` | who is signed in on this browser | gated like everything else |
| `/api/vaults` | vault creation, note read/write/search/history | the vault itself |
| `/api/events` | live server-sent event stream | carries vault activity, so it is **gated** |
| `/api/auth` | client-token minting and revocation | |
| `/api/mode` | the operating mode | changes the attack surface |
| `/api/exposure` | tunnel guidance, the public-URL self-test, the hardening checklist | |
| `/api/gateway` | tool profiles: which vaults and tools a client sees | |
| `/api/secrets` | upstream credentials — **write-only**, no read path exists | |
| `/api/market` | the marketplace and its install/uninstall flows | runs containers |
| `/api/stash` | the stash mirror | |
| `/api/directory` | the session directory mirror | |
| `/api/messenger` | the messenger mirror, read-only | |
| `/api/hooks` | outbound webhooks and their secrets | |
| `/api/automations` | event-triggered actions | |
| `/api/notifications` | the dashboard notification centre | |
| `/api/connect` | the connect page's client bundles (MCPB) | |
| `/api/backup` | downloads the whole hub home as one `tar.gz` (SPEC-604) — config, every vault, the OAuth store, **the upstream secret store and its encryption key** | the single highest-value response in this table: a full-home archive can impersonate the hub outright; **always mounted, gated like everything else in this section, streamed, never written to disk** |
| `/api/update` | release-channel update check against GHCR (SPEC-501) — read-only, outbound fetch is size/time-capped, "cannot check" is a state not an error | makes one outbound registry request |
| `/api/funnel` | local-only first-run funnel status — wizard-step timestamps, time-to-first-memory (SPEC-504) — **read-only**, never accepts a caller-supplied timestamp | every value it returns was set from a real server-side event, never from a request; `server/tests/funnel/test_no_egress.py` proves the whole path never opens a socket |
| `/api/_test` | a deliberately slow endpoint for shutdown testing | **only exists when `PALAIA_TEST_SLOW_ENDPOINT_SECONDS` is set**; never in a shipped hub |

| Threat | Mitigation as built | Where |
|---|---|---|
| Reaching any of the above with no session (A1, A2) | One ASGI gate over `/api/*` with a two-entry allowlist; it fails closed for *every* scope type, websockets included | `server/src/palaia_hub/admin_session.py`; a **route walk** over the app's own table asserts it in `server/tests/test_admin_session.py` |
| Cross-site request forgery (A7) | `SameSite=Lax` session cookie **plus** a double-submit token in `X-Palaia-CSRF` on every state-changing method | `server/src/palaia_hub/admin_session.py`, `web/src/lib/api/client.ts`, `server/tests/test_admin_session.py` |
| Forced sign-out from another site (A7) | `/oauth/logout` requires the same double-submit token — it sits outside `/api/*`, so the gate above does not cover it | `server/src/palaia_hub/oauth/routes.py`, `server/tests/oauth/test_login.py` |
| Guessing a session cookie (A1) | Gate refusals feed the failed-attempt limiter; the whole admin surface shares **one** bucket per caller, so walking routes buys no extra tries | `server/src/palaia_hub/modes/rate_limit.py`, `server/tests/security/test_admin_rate_limit.py` |
| Every caller sharing one bucket behind a proxy | The bucket key resolves `X-Forwarded-For` **only** from a loopback peer, and takes the last entry (the one nginx appended) | `server/src/palaia_hub/security/client_ip.py`, `server/tests/security/test_admin_rate_limit.py` |
| Clickjacking / sniffing / referrer leakage | A content-security policy per surface, `nosniff`, `no-referrer`, `DENY` framing, and HSTS when the request arrived over TLS | `server/src/palaia_hub/security/headers.py`, `server/tests/security/test_security_headers.py` |
| Script injection through vault content in the dashboard | The dashboard renders note bodies as text (React escapes); `dangerouslySetInnerHTML` appears nowhere in `web/src` | `server/tests/security/test_injection_surfaces.py` |
| Locking the operator out of a fresh hub | The gate stays open until a way in exists (an owner account or a provider), then latches closed on the next call | `server/src/palaia_hub/admin_session.py`, `server/tests/test_admin_session.py` |
| A full-home backup archive read by anyone but the owner (secrets, signing keys, every vault, in one download) | `GET /api/backup` (SPEC-604) sits behind the same admin gate as everything else in this table — no separate opt-in, no route that exists without it; the archive is built and streamed straight to the response body and never written to a temp file server-side, so there is no on-disk copy to leave world-readable even briefly; the dashboard's "Back up" button carries an explicit "store this like a password" warning | `server/src/palaia_hub/backup.py`, `server/src/palaia_hub/backup_api.py`, `server/tests/backup/test_routes.py`, `web/src/routes/Home.tsx` |
| A raw file copy of a SQLite store mid-write landing torn or missing WAL-resident rows in the archive | Every database is captured through SQLite's own online-backup API into an in-memory snapshot, not by copying bytes off disk — correct even while another connection holds the file open in WAL mode | `server/src/palaia_hub/backup.py`, `server/tests/backup/test_archive.py::test_a_sqlite_snapshot_includes_wal_resident_data_and_omits_the_wal_file` |

---

## 6. B3 — the authorization surface

**What is mounted.** `/oauth/authorize`, `/oauth/token`, `/oauth/register`,
`/oauth/revoke`, `/oauth/login`, `/oauth/logout`, `/oauth/idp/start`,
`/oauth/idp/callback`, and the discovery documents
`/.well-known/oauth-authorization-server`,
`/.well-known/openid-configuration`, `/.well-known/jwks.json` and
`/.well-known/oauth-protected-resource/{profile}`.

| Threat | Mitigation as built | Where |
|---|---|---|
| Authorization-code interception | PKCE is required on every authorization request; codes are one-time and short-lived | `server/src/palaia_hub/oauth/pkce.py`, `server/src/palaia_hub/oauth/service.py`, `server/tests/oauth/test_authorize.py` |
| Token forgery | ES256, asymmetric; the private key never leaves `<home>/oauth/signing-key.pem`; the resource side verifies with fastmcp's own `JWTVerifier` | `server/src/palaia_hub/oauth/keys.py`, `server/src/palaia_hub/oauth/verifier.py`, `server/tests/oauth/test_keys.py` |
| Password brute force | argon2id, a per-account failed-attempt lockout, and one identical failure message for every reason | `server/src/palaia_hub/oauth/login.py`, `server/tests/oauth/test_login.py` |
| Probing whether a hub is set up | A constant-time miss when no owner account exists | `server/src/palaia_hub/auth/hashing.py`, `server/tests/oauth/test_login.py` |
| Login CSRF (signing the victim into the attacker's session) | A double-submit token on the login form itself | `server/src/palaia_hub/oauth/login.py`, `server/tests/oauth/test_login.py` |
| Session fixation | A session id is minted by the server at sign-in and never accepted from the client; setting the owner password clears every existing session in the same statement | `server/src/palaia_hub/oauth/store.py`, `server/tests/security/test_session_and_cookies.py` |
| A session cookie read by script, or sent cross-site | `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` whenever the issuer is https (and deliberately not when it is not — a LAN hub must still be able to sign its operator in) | `server/src/palaia_hub/oauth/routes.py`, `server/tests/security/test_session_and_cookies.py` |
| An incomplete sign-out | The session row is deleted server-side, not just the cookie cleared; the CSRF cookie goes with it, so no token outlives the session it belonged to | `server/src/palaia_hub/oauth/routes.py`, `server/tests/security/test_session_and_cookies.py` |
| Open redirect with a fresh session attached | `next` is refused unless it is a local dashboard path or the authorization endpoint | `server/src/palaia_hub/oauth/routes.py`, `server/tests/oauth/test_login.py` |
| Credential spraying | The failed-attempt limiter covers `/oauth/token`, `/oauth/login`, `/oauth/register`, `/oauth/revoke` and `/oauth/logout` in `cloud`/`open` | `server/src/palaia_hub/modes/rate_limit.py`, `server/tests/modes/test_rate_limit.py` |
| Credentials in logs | No handler in the OAuth package logs a request line, query string or form body; a redaction filter masks every credential shape as a second line of defense | `server/src/palaia_hub/logging.py`, `server/tests/oauth/test_redaction.py`, `server/tests/security/test_no_credentials_in_logs.py` |
| A stale grant living forever | Refresh grants and login sessions are pruned on a schedule and on demand | `server/src/palaia_hub/oauth/store.py`, `server/tests/oauth/test_store.py` |

---

## 7. B4, B5, B6 — upstreams, installs, the curator, and the disk

### 7.1 Upstream MCP servers (B4)

| Threat | Mitigation as built | Where |
|---|---|---|
| Upstream credentials in plain text | Encrypted at rest under a Fernet key; never in `config.yaml`, never in a REST response, never in a log or an error message | `server/src/palaia_hub/upstream/secrets.py`, `server/tests/upstream/test_secret_never_leaks.py` |
| A read path appearing on the secret store | No response model in the package has a field a value could be placed in; `/api/secrets` is write-only by construction | `server/src/palaia_hub/upstream/api.py`, `server/tests/upstream/test_api.py` |
| An unreachable or hostile upstream stalling the hub | Probing is background-only; a `stdio` child is reaped at shutdown | `server/src/palaia_hub/upstream/monitor.py`, `server/tests/upstream/test_down_upstream.py` |

### 7.2 Marketplace installs (B5)

| Threat | Mitigation as built | Where |
|---|---|---|
| A tampered curated index | The index is signed; verification happens before any entry is used, with a last-good fallback | `server/src/palaia_hub/market/curated.py`, `server/tests/market/test_curated.py` |
| Installing something other than what was reviewed | Installs pin an image digest and record it | `server/src/palaia_hub/market/install.py`, `server/tests/market/test_install.py` |
| Container escape / host access | The container runs as a non-root user with no added capabilities; see `v3/deploy/` | `v3/deploy/docker-compose.yml` |

Running third-party code on the user's machine is the largest residual risk
in this document. See [§8](#8-accepted-risks-and-open-gaps).

### 7.3 The curator (B6)

The curator is a model with a **narrowed** tool profile (seven actions) and
its own guard middleware, so a prompt-injected curator cannot reach tools it
was not given. *Enforced by* `server/src/palaia_hub/curator/profile.py` and
`server/src/palaia_hub/curator/middleware.py`; *proven by*
`server/tests/curator/test_guard_matrix.py`.

### 7.4 Everything on disk (A3)

One rule, one implementation: **`0600` files inside `0700` directories, for
every store, write-ahead siblings included.** `server/src/palaia_hub/security/files.py`
owns it; every store calls into it; `server/tests/security/test_store_file_modes.py`
exercises every store into one hub home and then walks the tree, so a store
added later is covered the day its first write lands.

Two findings from this pass are fixed there: SQLite's `-wal`/`-shm`
siblings were created under the process umask (world-readable) next to
`0600` databases, and `config.yaml` — which holds the identity provider's
`client_secret` — was created world-readable in a world-traversable home.

### 7.5 The parser (A6)

`parse_note` never raises on user content (format spec invariant 3). That is
fuzzed with hypothesis, seeded from the golden conformance corpus, inside a
stated time budget: `server/tests/security/test_parser_fuzz.py`.

---

## 8. Accepted risks and open gaps

Each of these is a conscious decision, not an oversight. A reviewer should
argue with them; that is what the list is for.

1. **Prompt injection through tool results and vault content is not
   prevented.** A hostile upstream (A5) or a hostile note (A6) can put
   instructions in front of the user's assistant. The hub's answer is
   containment, not detection: profiles narrow what any client can reach,
   the curator runs under a guard, and installing an upstream is an explicit
   act with a visible permission list. No content filtering is attempted,
   because a filter that catches 90% of injections mostly teaches users to
   trust the other 10%.
2. **A marketplace install runs third-party code on the user's machine.**
   Mitigated by digest pinning, a signed index and container posture — not
   eliminated. Sandboxing beyond the container boundary is out of scope for
   3.0.
3. **The failed-attempt limiter is per-process and in memory.** It is a
   first line of defense for a single hub, not a distributed limiter. Every
   endpoint it covers has its own cryptographic defense underneath.
4. **`locked` mode trusts the LAN.** A hub on a private network with no
   sign-in is reachable by anything else on that network (A2). This is the
   zero-config first run the product depends on; the mode table is the
   control, and the dashboard says so in plain language.
5. **The vault is plain files.** Anyone who can read the user's home
   directory can read the vault, with or without palaia. Encrypting it would
   break the "your memory is files you own" promise the product is built on.
6. **Signing-key rotation is manual.** `kid` is the key's thumbprint and the
   JWKS can carry two keys during an overlap, but nothing rotates on a
   schedule. Deciding when to rotate is an operator action.
7. **HSTS is not sent on a plain-HTTP hub, by design.** A LAN hub that
   pinned itself to HTTPS would become unreachable. It is sent as soon as a
   request arrives over TLS — see `docs/exposure.md`.
8. **No hardware-backed key storage.** The signing key and the secret-store
   key are files, protected by file modes and by whatever the host provides.
9. **A backup is not one atomic snapshot across every store.** Each
   individual file in the archive is internally consistent (every SQLite
   database goes through the engine's own online-backup API; every other
   file is written atomically, so a read mid-write only ever sees the whole
   old or whole new content — see `server/src/palaia_hub/backup.py`'s
   module docstring). There is no cross-store quiesce lock, so two stores
   written to in the same second could land a moment apart in one archive.
   Building a global write-freeze was explicitly out of scope for this pass
   ("use what each store already supports, don't invent" — SPEC-604); for a
   single-operator personal hub with no distributed transaction spanning
   multiple stores, that gap is not a real exposure.
10. **A vault registered at a path outside the hub home is not covered.**
    `GET /api/backup` archives the hub home directory; a vault created at a
    custom absolute path elsewhere on disk (`vault_registry.py` allows this)
    is not inside it. The default "create a vault" flow always places one
    under the home, so this only affects an operator who deliberately chose
    a custom location — documented in `v3/docs/backup-restore.md`, not
    silently missed.

---

## 9. What changed in this pass

Findings from SPEC-502 that are **fixed in the code**, each with its test:

| Finding | Fix |
|---|---|
| SQLite write-ahead siblings world-readable next to `0600` databases | `server/src/palaia_hub/security/files.py`, applied by every store |
| Nine stores never narrowed their files at all | same module; `server/tests/security/test_store_file_modes.py` |
| `config.yaml` (identity-provider `client_secret`) world-readable | `server/src/palaia_hub/config.py` |
| No security headers on any browser surface | `server/src/palaia_hub/security/headers.py` |
| Admin-gate 401/403s never reached the rate limiter | middleware order in `server/src/palaia_hub/app.py`, plus the admin bucket in `server/src/palaia_hub/modes/rate_limit.py` |
| Every caller behind the packaged nginx shared one rate-limit bucket | `server/src/palaia_hub/security/client_ip.py` |
| `/oauth/logout` was a state-changing surface with no CSRF token | `server/src/palaia_hub/oauth/routes.py` |
| `session_secret=` matched none of the log-redaction patterns | `server/src/palaia_hub/logging.py` |
| The packaged image's nginx never proxied `/oauth` or `/.well-known`, so the sign-in door was unreachable in the container | `v3/deploy/nginx.conf.template` |

---

## 10. How to re-run the evidence

```bash
cd v3
uv sync
uv run pytest server/tests/security -q      # this document's own suite
uv run pytest server/tests -q               # everything
cd web && npm ci && npm test                # the dashboard's half of the CSRF contract
```

See [external-review-brief.md](external-review-brief.md) for the full
walk-through a reviewer needs.
