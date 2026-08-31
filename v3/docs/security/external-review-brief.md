# palaia v3 — Brief for an external security review

> You have been hired to look at this system before its 3.0 release. This
> document exists so that your first day is spent finding problems rather
> than working out what the thing is.
>
> Read [threat-model.md](threat-model.md) next; it is the claim, and your job
> is to test it. This page is the map.

---

## Scope

**In scope, in priority order:**

1. **The authorization server** — OAuth 2.1 with PKCE, dynamic client
   registration, the local owner password, the optional identity-provider
   sign-in, and the ES256 access tokens all of it mints.
2. **The admin session gate** — the owner session in front of the whole REST
   surface, its CSRF contract, and the mode policy that decides when it is
   mandatory.
3. **The MCP gateway** — per-profile authentication, per-token scoping, and
   the boundary between a client's tools and the vaults behind them.
4. **The secret store** — upstream credentials at rest, and the claim that
   there is no read path out of the hub.
5. **Everything on disk** — file modes, and what a second local account can
   read.
6. **The parser and the renderers** — the paths untrusted content takes from
   a Markdown file to a browser or an AI client.
7. **The backup archive (`GET /api/backup`, SPEC-604)** — the one response
   in the whole system that intentionally contains everything: every
   secret, every key, every vault, in one file. Its gating, its
   consistency claim, and the fact that it never touches disk server-side
   deserve the same scrutiny as the secret store itself.

**Explicitly out of scope for this engagement:**

- palaia v2 (the repository root). It is a different product on a
  maintenance branch and shares no code with v3.
- The published container image's base OS and its distribution packages.
- Prompt-injection resistance of the *models* connected to the hub. The hub
  contains its blast radius (threat model §8.1); it does not try to detect
  injections.
- Availability and denial of service beyond the failed-attempt limiting
  described below. A hub is a single process on someone's own machine.

---

## Architecture in one page

```
                          ┌───────────────────────────────┐
   AI clients  ──MCP──▶   │                               │
   (Claude, Codex,        │        palaia hub             │ ──▶  vault (Markdown files + git)
    ChatGPT, CLI)         │   one FastAPI/ASGI process    │ ──▶  index (SQLite + FTS + vectors)
                          │                               │ ──▶  stores (SQLite, see below)
   a browser  ──HTTP──▶   │                               │
   (the dashboard)        └───────────────────────────────┘
                                    │          │
                                    │          └──▶  upstream MCP servers (http or stdio child)
                                    └──▶  the curator (a model, narrowed tool profile)
```

**One process, four HTTP surfaces**, each with its own authentication story:

| Surface | Auth | Entry point in the code |
|---|---|---|
| `/mcp*` | bearer `plt_…` token or OAuth access token, verified per profile | `server/src/palaia_hub/gateway/` |
| `/api/*` | owner session cookie + `X-Palaia-CSRF` | `server/src/palaia_hub/admin_session.py` |
| `/oauth/*`, `/.well-known/*` | none — this is where credentials are minted | `server/src/palaia_hub/oauth/routes.py` |
| `/` | none — static markup; all data comes from `/api/*` | `server/src/palaia_hub/static.py` |

**Assembly order matters and is worth reading first:**
`server/src/palaia_hub/app.py`'s `create_app` builds the middleware stack
(security headers → failed-attempt limiter → session gate → routes), mounts
the MCP endpoints before the dashboard catch-all, and wires every optional
router behind the store it needs.

**The stores**, all under one hub home (`PALAIA_HOME`, or the platform data
directory):

| File | Contents |
|---|---|
| `config.yaml` | the hub's configuration, including an identity provider's client secret |
| `oauth/signing-key.pem` | the ES256 private key |
| `oauth/oauth.sqlite3` | clients, codes, grants, login sessions, the owner account |
| `tokens.yaml` | client tokens (argon2id hashes) |
| `secrets.key`, `secrets.sqlite3` | upstream credentials, Fernet-encrypted |
| `stash.db`, `directory.db`, `messenger.db` | agent hand-offs, sessions, messages |
| `notifications.sqlite3`, `hook-outbox.sqlite3`, `automations-outbox.sqlite3` | queues |
| `market_*.json`, `market_manual.sqlite3`, `registry_cache/` | marketplace caches |
| `mode_audit.jsonl` | every mode change, accepted or refused |

---

## Entry points worth reading, in order

1. `server/src/palaia_hub/app.py` — the assembly. Start here.
2. `server/src/palaia_hub/admin_session.py` — the session gate and its CSRF
   contract. The module docstring states the policy; the middleware
   implements it.
3. `server/src/palaia_hub/oauth/service.py` — every protocol decision. The
   routes module beside it is deliberately thin.
4. `server/src/palaia_hub/oauth/store.py` — all persistent authorization
   state, and its transaction discipline.
5. `server/src/palaia_hub/auth/scopes.py` and `auth/policy.py` — what a
   token may reach, and the refusal to start an unauthenticated MCP endpoint.
6. `server/src/palaia_hub/modes/` — the mode table, the rate limiter, the
   tunnel path scoping, the hardening checklist.
7. `server/src/palaia_hub/security/` — file modes, response headers, and the
   per-caller identity the limiter keys on.
8. `server/src/palaia_hub/upstream/secrets.py` — the encrypted store, and the
   stated rule that no value ever leaves the process.
9. `server/src/palaia_hub/backup.py` — the whole-home archive, its
   file-by-content SQLite snapshotting, and the honest statement of what its
   consistency guarantee is (and is not).

---

## How to run everything locally

No Docker daemon is required for the test suite; container-dependent tests
skip themselves honestly.

```bash
git clone <this repository>
cd v3

# Python: install, lint, type-check, test
uv sync
uv run ruff check .
uv run mypy server/src
uv run pytest server/tests -q

# The security suite specifically
uv run pytest server/tests/security -q

# The end-to-end scenarios (real hub subprocesses, real HTTP)
uv run pytest server/tests/e2e -q

# The dashboard
cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run build
```

**Run a hub and poke at it:**

```bash
cd v3
export PALAIA_HOME=/tmp/palaia-review          # never your real home
uv run palaia-hub serve --host 127.0.0.1 --port 8420
# in another shell:
curl -s localhost:8420/api/info | jq
curl -si localhost:8420/api/vaults             # 401 once a sign-in exists
```

**Turn the authorization server on** (this is what makes `/oauth/*` real):

```bash
uv run palaia-hub oauth set-password           # creates the single owner account
# then set `oauth.enabled: true` and an `oauth.issuer` in $PALAIA_HOME/config.yaml
```

**Reproduce the three modes:** set `mode:` in `config.yaml` to `locked`,
`cloud` or `open` and restart. `open` is refused unless a way to sign in
exists — that refusal is itself a control, see threat model §2.

**The packaged image** (needs a Docker daemon):

```bash
docker build -f v3/deploy/Dockerfile -t palaia-hub:review .
cd v3/deploy && docker compose up -d
```

---

## What we already believe, and what we want challenged

The complete list of controls, with the module and test behind each, is
[threat-model.md](threat-model.md) §§4–7. The questions we would most like an
outside answer to:

1. Is the double-submit CSRF pair actually unforgeable in every flow we use
   it in — including the identity-provider round trip, where the cookie is
   set on a redirect from a third party?
2. Does the session gate's "stay open until a way in exists" latch have a
   race we have not seen? It is the one place the system is deliberately
   open.
3. Is ES256 with a thumbprint `kid` and no rotation schedule defensible for
   a product with this lifetime? (We chose ES256 over Ed25519 because the
   resource-side verifier we are required to use rejects EdDSA — see
   `server/src/palaia_hub/oauth/keys.py`.)
4. Can a tool argument or a vault note reach a rendered surface unescaped by
   a path our tests do not cover?
5. Is the failed-attempt limiter's proxy handling (`X-Forwarded-For` from a
   loopback peer only, last entry wins) sound for every deployment shape we
   ship?
6. `GET /api/backup` has no opt-in parameter and mounts unconditionally,
   specifically so it can never exist without the admin session gate
   wrapping it. Is that construction actually load-bearing, or is there a
   path (a future refactor of `create_app`, a different app assembly for
   some deployment shape) where it could end up exposed?

## Accepted risks

These are decisions, not omissions. The full text and the reasoning behind
each is in [threat-model.md](threat-model.md) §8; in short:

1. Prompt injection through tool results and vault content is contained, not
   prevented.
2. A marketplace install runs third-party code on the user's machine.
3. The failed-attempt limiter is per-process and in memory.
4. `locked` mode trusts the local network.
5. The vault is plain, unencrypted files — deliberately.
6. Signing-key rotation is manual.
7. HSTS is not sent on a plain-HTTP hub.
8. There is no hardware-backed key storage.

We would rather be told one of these is wrong than have it politely accepted.

---

## Reporting what you find

Use the process in [`../../SECURITY.md`](../../SECURITY.md). For an engaged
reviewer, a single report at the end plus immediate notification of anything
critical is the shape we expect.
