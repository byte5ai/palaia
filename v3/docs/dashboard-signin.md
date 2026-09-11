# Signing in to the dashboard

> **Normative.** Implements [SPEC-401](../specs/SPEC-401-dashboard-signin.md):
> the admin session gate in `palaia_hub.admin_session`, its wiring in
> `palaia_hub.app.create_app`, and the dashboard's half in
> `v3/web/src/lib/api/client.ts` and `v3/web/src/lib/session.ts`.
> MASTERPLAN §5.5 is the binding policy; this document explains how it is
> implemented, not why it was chosen.

## 1. One door, reused

There is no separate dashboard account. The session the dashboard uses **is**
the sign-in session the hub already had: the `palaia_oauth_session` cookie
minted by the owner password form (`/oauth/login`) or by a configured sign-in
provider (`/oauth/idp/start`) — whichever this hub has, never both
(MASTERPLAN §5.5's "one door only" rule).

Consequences worth stating:

- Setting a password — the first-run wizard's owner step
  (`POST /api/auth/owner`, accepted only while no account exists; issue
  #342) or `palaia-hub oauth set-password` — or configuring a provider is
  what creates the dashboard's account, too.
- Session lifetime is `oauth.session_ttl` (default 12 hours). There is no
  separate dashboard timeout and no remember-me.
- Signing out (`POST /oauth/logout`) ends the session for both surfaces.

## 2. What the gate covers

`palaia_hub.admin_session.AdminSessionMiddleware` sits in front of the whole
app and looks at one prefix:

| Surface | Gated? | Why |
|---|---|---|
| `/api/*` | **yes**, except the allowlist below | the admin surface: vault contents, tokens, hooks, mode changes |
| `/api/health`, `/api/info` | no | a liveness probe, and the non-secret "how do I sign in here" answer the sign-in page itself needs |
| `/api/events` | **yes** | the live stream carries vault activity, note titles and mode changes |
| `/oauth/*` | no | the door itself — gating it would be a lock-out |
| `/mcp/*` | no | MCP clients carry their own bearer/OAuth access tokens, verified in the gateway |
| the dashboard build (`/`, static files) | no | the shell is not a secret; every byte of data it renders comes from `/api/*` |

A refused request answers JSON with a plain-language `detail` and the
`sign_in_url` of this hub's one door — which is what lets the dashboard's API
client turn any 401 into a single redirect to the right page, password or
provider, without knowing which one exists.

## 3. When the gate is active

| Mode | Default | Can the operator change it? |
|---|---|---|
| **Open** | on | no — mandatory (a config that sets `dashboard.require_sign_in: false` here is refused at load) |
| **Cloud** | on | yes — `dashboard.require_sign_in: false` |
| **Locked** | off | yes — `dashboard.require_sign_in: true` |

And in every mode, only **once there is a way in**: an owner account or a
configured provider, plus `oauth.enabled` and an `oauth.issuer`. Before that
the gate stays open, because otherwise the first-run wizard — the flow that
creates the account — would be unreachable and a fresh hub would be a brick.
The check is made per request against the live store, so the gate closes on
the next call after the wizard creates the owner; no restart.

## 4. CSRF on the REST surface

State-changing methods (`POST`/`PUT`/`PATCH`/`DELETE`) under `/api/*` must
carry the double-submit token the sign-in flow set, in the
`X-Palaia-CSRF` header:

- signing in sets `palaia_oauth_csrf` for the session's lifetime — readable
  by script *on purpose*, since the dashboard has to echo it;
- the session cookie next to it stays `HttpOnly`, `SameSite=Lax`,
  `Secure` whenever the issuer is https;
- the header and the cookie must match (constant-time compare), and both
  must be present — a session with no token cannot be waved through;
- `GET`/`HEAD`/`OPTIONS` need no token: they change nothing, and
  `EventSource` cannot send headers at all.

The dashboard sends the header on every mutating call from one place
(`web/src/lib/api/client.ts`); no component issues a bare `fetch`.

## 5. Open mode, and issue #242

`open` mode was refused outright while no dashboard sign-in existed. It is
accepted again, on one condition: the hub must have a way in
(§3). Both operator entry points enforce it — `load_config` (a hand-edited
`config.yaml`) and `POST /api/mode` (the exposure wizard, which checks the
*candidate* configuration and refuses before writing, so the wizard never
persists a file the hub would then refuse to start from).

## 6. What this is not

No multi-user accounts or roles; no remember-me beyond `oauth.session_ttl`;
no rate limiting of its own (the auth paths are already covered in
cloud/open — see [exposure.md](exposure.md) §5).
