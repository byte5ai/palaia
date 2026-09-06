# palaia Access Modes & the Exposure Wizard

> **Normative.** Implements [SPEC-205](../specs/SPEC-205-modes-exposure.md):
> the REST surface behind `palaia_hub.modes`, and the dashboard's "Access
> mode" page (`v3/web/src/routes/Exposure.tsx`). MASTERPLAN §5.5 is the
> binding policy this document explains, not re-derives.

## 1. The three modes, and what actually changes

| Mode | MCP endpoints | Admin dashboard | Sign-in |
|---|---|---|---|
| **Locked** | your network only | your network only | optional |
| **Cloud** | public (via a tunnel) | your network only | mandatory |
| **Open** | public | public | mandatory + hardening checklist |

This table (MASTERPLAN §5.5) is enforced in code, in two layers:

1. **Config-load time** (`palaia_hub.config.HubConfig`) — `cloud`/`open`
   refuse to load at all without `auth_enabled` or `oauth.enabled`; `cloud`
   additionally refuses a public/wildcard bind address (the dashboard must
   stay off the same public listener a tunnel can reach).
2. **Wizard time** (`palaia_hub.modes.policy.build_candidate_config`) — the
   same rule, checked *before* anything is written to disk, plus two
   wizard-specific checks config-loading has no reason to make: an
   `oauth.enabled` with no `oauth.issuer`, and an `exposure.public_url`
   that is not `https://`.
3. **Request time** (`palaia_hub.admin_session.AdminSessionMiddleware`) — the
   "Sign-in" column of the table above, for the *dashboard* rather than for
   MCP: every `/api/*` route needs a live owner session, mandatory in Open,
   on by default in Cloud, opt-in in Locked. See
   [dashboard-signin.md](dashboard-signin.md), which also covers why Open
   mode is refused on a hub that has no way to sign in at all (issue #242).

**The vendor-cloud reality check, stated plainly:** claude.ai and ChatGPT
connect to a custom connector *from their own vendor cloud*, never from
your device. In Locked mode they cannot reach palaia no matter what your
local network looks like — Cloud mode (a tunnel pointed at the MCP
endpoint) is the sweet spot for "I want claude.ai/ChatGPT/my phone to reach
my memory"; Open mode is only for someone who deliberately wants the
dashboard itself on the internet too.

## 2. The mode-change API

`GET /api/mode` returns two states, not one:

```json
{
  "active_mode": "locked",
  "configured_mode": "cloud",
  "restart_required": true,
  "host": "127.0.0.1",
  "auth_enabled": true,
  "oauth_enabled": false,
  "oauth_issuer": null,
  "public_url": null,
  "tunnel": null
}
```

`active_*` is what the **running process** was actually built from;
`configured_*` is what is currently on disk (`config.yaml`). They differ
whenever a change has been saved but the hub has not restarted yet — the
hub does not pretend a running gateway/OAuth server reconfigured itself
live; `restart_required` says so honestly instead.

`POST /api/mode` accepts any subset of `mode`, `host`, `auth_enabled`,
`oauth_enabled`, `oauth_issuer`, `public_url`, `tunnel` — omitted fields
keep their current value. Two things happen on every call, success or
refusal:

- **An audit entry** is appended to `mode_audit.jsonl` under the hub's home
  directory (`from_mode`, `to_mode`, `accepted`, `reason`, `changed_keys`,
  a stable `id` and timestamp) — a refused attempt is itself a
  security-relevant signal and is kept, not discarded.
- **On acceptance only**, an `hub.mode_changed` event is published on the
  event bus (`from_mode`, `to_mode`, `restart_required`, `changed_keys` —
  see `docs/events.md` §3) and the change is written into `config.yaml` by
  patching only the touched keys — every comment and every untouched
  setting survives byte-for-byte (`palaia_hub.modes.patch`; PyYAML has no
  round-trip mode that preserves comments, so this edits the file as text
  rather than re-serializing it).

A change to `mode`, `host`, `auth_enabled`, `oauth.enabled` or
`oauth.issuer` needs a hub restart to take effect (those build the
gateway/OAuth wiring once, at startup). A change to only
`exposure.public_url`/`exposure.tunnel` is live immediately — nothing at
startup depends on either; they exist purely to back the wizard's own UI
(the connect-a-client page's filled-in address, the self-test's target).

**Deviation, stated plainly:** the dashboard's Access mode page changes
`mode` and the sign-in requirement only. `host`, `oauth.enabled` and
`oauth.issuer` are accepted by the API (so a future page, or `curl`, can
set them) but are not yet exposed as form fields in the wizard itself —
enabling OAuth sign-in for claude.ai/ChatGPT today means setting
`oauth.enabled`/`oauth.issuer` in `config.yaml` by hand (the onboarding
wizard's first step, or SPEC-108's `palaia-hub oauth set-password`, sets
the account itself). The wizard
surfaces the *result* the moment it is configured (§4 below) even though
it does not yet drive the configuration.

## 3. Tunnel guidance

`POST /api/exposure/tunnel` with `{"kind": "tailscale" | "cloudflared", "hostname"?: string, "local_port"?: number}`
returns a ready-to-use config plus the commands that apply it. Both
providers scope what they forward to exactly what the current mode needs:

- **Cloud mode** forwards only `/mcp`, `/oauth` and `/.well-known` — the
  MCP endpoint and the sign-in pages a remote browser needs to complete an
  OAuth login, nothing else. The dashboard and the REST admin API stay off
  the tunnel entirely, matching §1's table even once a tunnel makes the box
  reachable from the internet.
- **Open mode** forwards everything (`/`).

`GET /api/exposure` additionally reports which of `tailscale`/`cloudflared`
were found on the host (a plain `shutil.which` lookup — `palaia_hub.modes.detect`;
neither binary is shelled out to). Detecting neither still offers both
configs, plus "I have my own reverse proxy", which gets no generated
config at all — just the same path-scoping rule stated in prose.

## 4. The public-URL self-test — no fake green

`POST /api/exposure/selftest` with `{"public_url": "..."}` makes the hub
fetch `<public_url>/api/info` **itself** and reports exactly what
happened: reachable with a real latency, or unreachable with the real
reason (a non-2xx status, a connection error, a timeout — never a generic
"failed"). Nothing in the wizard claims a public URL works without this
check actually having passed.

## 5. Auth-endpoint rate limiting

Mounted only when `mode` is `cloud`/`open` (`palaia_hub.modes.rate_limit.AuthRateLimitMiddleware`,
wired in `palaia_hub.app.create_app`) — `locked` mode has no public attack
surface to throttle. It throttles **failures, not volume**: a
`(client IP, path)` bucket only fills when the endpoint's own response was
itself a failure (status ≥ 400). A legitimate burst of successful traffic
— the exact multi-device refresh fan-out MASTERPLAN §5.5 calls out as the
"mcp-hub daily re-login incident" this hub must not reproduce — is never
throttled; repeated *failed* logins, token requests or registrations are.
Covers `/oauth/token`, `/oauth/login`, `/oauth/register`, `/oauth/revoke`,
`/oauth/logout`, and `POST /api/auth/tokens`.

**SPEC-502 added two things to this** (see
[security/threat-model.md](security/threat-model.md) §5):

- **The admin surface is covered too.** SPEC-401's session gate refuses an
  unauthenticated caller with a 401, and those refusals now fill a bucket
  of their own — one shared bucket per caller for the whole of `/api/*`,
  so walking routes does not buy ten fresh tries per route. `/api/health`
  and `/api/info` are never throttled: the sign-in page reads them, and a
  locked-out operator must still be able to see that the hub is alive.
- **The caller is identified correctly behind a reverse proxy.** In the
  packaged image nginx is the only public listener and the hub sees
  loopback for every request, which used to collapse every caller into one
  bucket — no per-attacker limit, and one attacker locking out everyone.
  The bucket key now reads `X-Forwarded-For` **only** when the immediate
  peer is loopback, and takes its **last** entry — the one the proxy
  appended, which a caller cannot forge (`palaia_hub.security.client_ip`).

## 5b. Browser-hardening headers, and HSTS

Every response the hub serves carries `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`,
`Cross-Origin-Opener-Policy: same-origin`, a `Permissions-Policy`, and a
content-security policy chosen per surface — a strict one for the
dashboard, a stricter "nothing at all" one for the sign-in pages (which
carry no script), and a deny-everything one for `/api/*` and `/mcp/*`,
which nothing should ever render (`palaia_hub.security.headers`). The
packaged image's nginx repeats the same set on the static dashboard it
serves directly.

**`Strict-Transport-Security` is sent only when the request actually
arrived over TLS** — learned from `X-Forwarded-Proto` behind a tunnel or
reverse proxy, or from the connection itself. This is the one hardening
header that must not be a default: a browser that pinned
`http://palaia.local` to HTTPS could not reach a LAN hub at all. So it
appears exactly when it should — the moment you put a tunnel in front of
the hub — and never before. If you terminate TLS in your own reverse proxy,
make sure it forwards `X-Forwarded-Proto`, or the header will not be sent.

## 6. The Open-mode hardening checklist

`GET /api/exposure`'s `checklist` array states, per item, whether the hub
verified it itself (`auto: true`, `passed: true|false`) or whether only the
operator can confirm it (`auto: false`, `passed: null`):

| Item | Verified how |
|---|---|
| Sign-in is required | Auto — `auth_enabled` or `oauth.enabled`. |
| Auth endpoints are rate-limited | Auto — whether §5's middleware is actually mounted. |
| The public URL serves valid TLS | Auto once a self-test has run against it (a successful fetch implies a valid handshake); manual, "not checked yet", until then. |
| The owner account has its own password | Auto when the caller has OAuth-store access to check; manual otherwise. Open mode additionally *refuses to load* without it — see [dashboard-signin.md](dashboard-signin.md) §5. |
| You understand the dashboard itself is now public | Always manual — a conscious choice, not a fact to verify. |

## 7. Why this stays dashboard-only

Per `docs/design/principles.md`'s access table and MASTERPLAN §4 rule 8's
standing question ("is an MCP App the right surface for this?"): **no** —
access mode, exposure and token revocation change the attack surface
itself, which is exactly the category of action Lume's principles reserve
for the dashboard alone, never an in-chat surface. Every route in this
document is under `/api/mode` and `/api/exposure`, not part of any MCP
tool family, and the dashboard page is not wrapped as an MCP App.
