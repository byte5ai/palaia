# Client integration matrix — validation results

> **Normative evidence log.** Implements [SPEC-209](../specs/SPEC-209-client-matrix.md):
> proof (and honest non-proof) for every row of [MASTERPLAN §6](../MASTERPLAN.md#6-client-integration-matrix),
> against a real Cloud-mode (`mode: cloud`, `oauth.enabled: true`) hub. The
> honesty rule from the SPEC is binding here too: **"not verified" is an
> acceptable cell value; a green cell requires evidence** (a command, and
> its actually-observed output). Nothing below is asserted from memory of
> how a client "should" behave.
>
> Scripted evidence lives in
> [`v3/server/tests/e2e/test_spec209_client_matrix.py`](../server/tests/e2e/test_spec209_client_matrix.py)
> (real hub, real `claude` CLI 2.1.241) and the pre-existing
> [`v3/server/tests/oauth/test_flow_e2e.py`](../server/tests/oauth/test_flow_e2e.py)
> (SPEC-203's own scripted OAuth client, exercising the DCR and CIMD paths
> every remote client in the matrix uses one of). Both suites were run for
> real while writing this document (see §0).

## 0. What was actually run, and when

```
$ cd v3 && uv run pytest server/tests/e2e/test_spec209_client_matrix.py -q
...                                                                      [100%]
3 passed in 74.10s (0:01:14)
```
Run twice in a row (74.10s, then 77.38s) with no flakes.

```
$ claude --version
2.1.241 (Claude Code)
```

Environment note carried through every cell below: this sandbox routes all
outbound HTTPS through a pre-configured proxy. The hub subprocess in the
test fixture sets `FASTMCP_SSRF_TRUST_PROXY=1` so FastMCP's SSRF-safe
fetcher (used for CIMD document fetches) can reach the real internet at all
— see [byte5ai/palaia#233](https://github.com/byte5ai/palaia/issues/233).
Without that variable, every CIMD-based login (claude.ai, ChatGPT, Codex,
Claude Code) fails at the metadata-fetch step in an egress-proxied
deployment, not just in this sandbox — worth a line in palaia's own ops
docs, tracked in that issue.

No other client binary (`codex`, `gemini`, an LM Studio/Open WebUI/llama.cpp
install, a ChatGPT or Grok account) was available in this environment. Those
rows are evidenced by (a) SPEC-203's own scripted-client test suite, which
exercises the exact wire-level behavior their published client SDKs use
(DCR, CIMD, resource-indicator variants, scope enforcement), and (b) web
research against each vendor's current documentation, cited per row — never
by running the real binary. That distinction is called out explicitly in
every such row.

## 1. Matrix

| # | Client | Cell | Verified how |
|---|---|---|---|
| 1 | Claude Code (CLI) | **Green, with two filed quirks** — §2 | Scripted, real CLI |
| 2 | Claude Desktop | Not verified — not built | N/A (Phase 3) |
| 3 | claude.ai (web/desktop/mobile/Cowork) | Not verified (no account in this environment); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 4 | ChatGPT | Not verified (no account); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 5 | Codex (CLI/IDE/desktop) | Not verified (binary unavailable); OAuth wire protocol (CIMD) shared with row 1 is green; **one connect-page correction shipped** — §3 | Scripted (shared code path) + docs |
| 6 | Antigravity / Gemini CLI | Not verified (binary unavailable); config shape confirmed correct against current docs | Docs |
| 7 | Grok | Not verified (no account); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 8 | OpenClaw | Not verified — not a v3 target (v2 serves it, per MASTERPLAN) | N/A |
| 9 | Local LLM frontends (LM Studio / Open WebUI / llama.cpp) | Not verified (no install available); **one connect-page correction shipped** (LM Studio) — §3 | Docs |

Every row has a filled cell; none of "not verified" above is silent —
each names exactly what would turn it green (a real account/binary in a
future validation run) and points at the evidence that *does* exist today.

## 2. Claude Code CLI — the full trace

Three real runs, in increasing depth, all against
`v3/server/tests/e2e/support/hub_server_oauth.py` — a real `VaultEngine`,
a real `AuthorizationServer` (SPEC-203), a real `uvicorn` socket, `mode:
cloud` (satisfies `HubConfig`'s own cloud-mode policy: private bind +
`oauth.enabled`). The one thing this sandbox cannot add on top is an actual
public tunnel — a network-reachability fact about Tailscale/cloudflared,
not part of the OAuth code path a *local* CLI client exercises. Claude Code
never goes through a vendor cloud in the first place, so it reaches this
loopback listener exactly as it would reach a tunnel's local termination
point.

### 2.1 A real OAuth token, real tool round trip

`test_a_real_oauth_token_lets_claude_code_round_trip_write_search_read`:
a scripted OAuth 2.1 + PKCE client (same protocol steps as
`test_flow_e2e.py`'s `ScriptedClient`, driven over a real `httpx.Client`
against a live TCP socket instead of the ASGI shortcut) completes a real
code flow — 401 → RFC 9728 discovery → RFC 8414 discovery → DCR → real
password sign-in → authorize → token exchange — against the real hub. The
resulting access token is handed to the real `claude` CLI via
`claude mcp add --transport http ... --header "Authorization: Bearer
<token>"`. `claude mcp get` reports `√ Connected`, and a real `claude -p`
session round-trips:

```
write : Call the mcp__palaia-spec209-e2e__work_memory_write tool with
        title='OAuth E2E' body='real oauth token round trip' → …
        {"permalink":"oauth-e2e","title":"OAuth E2E", …}
search: work_memory_search query='round trip' → hits: [{"permalink":"oauth-e2e", …}]
read  : work_memory_read permalink='oauth-e2e' → "real oauth token round trip"
```

This is real evidence that OAuth issuance and the resource server's
per-tool scope enforcement both work end to end with the actual CLI as the
MCP client — SPEC-203's engine and SPEC-209's client both proven together,
over a real socket.

### 2.2 A real, but non-blocking, status-display bug — filed as #232

`test_claude_mcp_get_reports_failed_to_connect_before_any_token_exists`:
before any token exists for a profile, `claude mcp get <name>` runs its own
connectivity probe and reports:

```
Status: × Failed to connect
Issue: Protected resource http://127.0.0.1:<port>/default does not match
       expected http://127.0.0.1:<port>/mcp/default/ (or origin)
```

Root cause: palaia's canonical audience shape
(`palaia_hub.oauth.resources.ResourceRegistry.audience` — deliberately
`<issuer>/<profile>`, fixing a named production incident, see that
module's docstring) never equals the gateway's actual mount URL,
`<issuer>/mcp/<profile>/`. Confirmed **not** a login blocker — §2.3 logs in
against the exact same profile moments later and `mcp get` then reports
`√ Connected` for it. Filed as
[byte5ai/palaia#232](https://github.com/byte5ai/palaia/issues/232) as a
UX/trust issue (a user who checks status before signing in sees a
scary-sounding, wrong verdict on a hub that works fine), not a functional
one.

### 2.3 The real login blocker — filed as #233 — and its confirmed workaround

`test_claude_code_cli_native_oauth_login_needs_a_preregistered_redirect_uri`
(skipped, not failed, when this sandbox cannot reach `claude.ai` — the
CIMD document fetch needs real internet):

**Part 1, the default zero-flag path** (`claude mcp add --transport http
... ` then `claude mcp login <name> --no-browser`, exactly the connect-page's
advertised one-liner): the CLI fetches Claude Code's own real, published
CIMD document (`https://claude.ai/oauth/claude-code-client-metadata`),
prints a real authorize URL, and — signed in for real as the owner — hits:

```
400 invalid_redirect_uri
"the redirect_uri does not exactly match one this client registered."
```

Root cause: Anthropic's CIMD document registers a **portless** loopback
redirect URI (`http://localhost/callback`); the CLI's real request always
carries a live ephemeral port; `palaia_hub.oauth.cimd.match_redirect_uri`
does byte-exact matching with no RFC 8252 §7.3 loopback-port exemption. The
port differs on every attempt, so this can never match — every default,
zero-flag Claude Code OAuth login fails, today, for everyone.

**Part 2, the documented CLI workaround, completed for real**: Claude
Code's own `mcp add --help` names exactly this scenario ("`--callback-port`:
Fixed port for OAuth callback, for servers requiring pre-registered
redirect URIs"). The test pre-registers a real DCR client with a literal,
fixed-port redirect URI, then:

```
$ claude mcp add --transport http palaia <url> \
    --client-id <that DCR client id> --callback-port <that port>
$ claude mcp login palaia --no-browser
Starting authentication for "palaia"…
Visit this URL to authorize: http://127.0.0.1:<port>/oauth/authorize?...
Waiting for authorization… (^C to cancel)
Or paste the redirect URL here: http://localhost:<port>/callback?code=...
Authenticated with "palaia". Its tools are now available in Claude Code.
$ claude mcp get palaia
Status: √ Connected
$ claude -p "call work_memory_write …" --allowedTools mcp__palaia__work_memory_write
{"permalink":"native-login-e2e","title":"Native Login E2E", …}
```

Exit code `0`. This proves the resource server, PKCE, DCR, and the CLI's
own OAuth plumbing are all fine — **only** the loopback-port exemption is
missing, and it specifically breaks the connect-page's no-extra-flags
promise. Filed as
[byte5ai/palaia#233](https://github.com/byte5ai/palaia/issues/233), with a
suggested direction (accept a presented loopback redirect URI that matches
a registered one on scheme/host/path but not port) flagged for an
owner/architect decision rather than patched here — it touches SPEC-203's
security-critical redirect-matching code and its existing exact-match
tests.

## 3. Connect-page corrections shipped in this PR

Both found by checking `v3/web/src/lib/clients.ts`'s one-liners against
each vendor's current real documentation (§0's "no binary available"
caveat applies — corrected against docs, not a live binary):

- **Codex**: was `codex mcp add palaia --transport http <url>` — Codex CLI
  has no `--transport` flag for `mcp add`; the real syntax (confirmed via
  [openai/codex#4904](https://github.com/openai/codex/pull/4904) and
  current third-party Codex CLI MCP guides) is
  `codex mcp add <name> --url <url> [--bearer-token-env-var VAR]`. Fixed to
  `codex mcp add palaia --url <url>`.
- **LM Studio**: was `{"palaia": {"url": "<url>"}}` with no enclosing
  `mcpServers` key at all — not a valid `mcp.json`. LM Studio's own docs
  ([lmstudio.ai/docs/app/mcp](https://lmstudio.ai/docs/app/mcp)) show
  `{"mcpServers": {"<name>": {"type": "streamable-http", "url": "<url>"}}}`
  for a streamable-HTTP server specifically (the plain `"url"`-only shape
  in their examples is for SSE). Fixed to include the `mcpServers` wrapper
  and `"type": "streamable-http"`.

Checked and found already correct, no change:

- **Claude Code CLI**: `claude mcp add --transport http palaia <url>` —
  matches exactly (§2 ran this literal command against a real hub).
- **Antigravity / Gemini CLI**: `~/.gemini/settings.json`'s `mcpServers.*.httpUrl`
  — confirmed against [geminicli.com/docs/tools/mcp-server](https://geminicli.com/docs/tools/mcp-server/)
  and the upstream `google-gemini/gemini-cli` docs.

## 4. Rows not exercised with a real vendor account/binary

For claude.ai, ChatGPT, Grok and Codex, no real account or binary was
available in this environment (§0). What *is* real evidence for these
rows: every one of them connects as a "remote MCP server" client following
the same RFC 9728 discovery → RFC 8414 discovery → DCR-or-CIMD →
PKCE-code-flow → bearer-token protocol that §2 just proved end to end with
Claude Code, and that `test_flow_e2e.py` (SPEC-203, pre-existing, still
green) exercises directly:

- `test_dcr_client_completes_the_whole_flow_and_calls_a_tool` — the classic
  RFC 7591 DCR path (ChatGPT/Grok's documented custom-connector flow, per
  `research/mcp-landscape-2026.md` §6).
- `test_cimd_client_needs_no_registration_step_at_all` — the MCP
  2026-07-28 CIMD path (Codex's documented `codex mcp login`, per the same
  research; also what Claude Code itself turned out to use — §2.3).
- `test_the_resource_indicator_with_a_trailing_mcp_segment_works_end_to_end`
  and `test_a_read_only_grant_cannot_call_a_write_tool` — the
  resource-indicator-shape and scope-enforcement behaviors any of these
  clients could hit.

Byte5ai/palaia#233's redirect_uri finding (§2.3) plausibly affects any of
these clients too **if** their own published CIMD/DCR redirect URI is a
portless loopback address the way Claude Code's is — genuinely not known
without their real client, so left "not verified" rather than guessed at.
ChatGPT and Grok are browser/mobile-first (not loopback-native-app clients
in the RFC 8252 sense), so they are less likely to hit it than a CLI is;
Codex, being another native CLI, is the one worth checking first once a
real Codex install is available.

## 5. Rows out of scope for this validation

- **Claude Desktop**: MCPB bundle not built yet (MASTERPLAN: Phase 3);
  `v3/web/src/lib/clients.ts` already states this honestly (`notYet`,
  with the reason and the Phase-3 note) — no correction needed.
- **OpenClaw**: not a v3 launch target (v2's plugin serves it) — nothing
  to validate under SPEC-209.
- **Local LLM frontends** (LM Studio, Open WebUI, llama.cpp): no install
  available (§0); LM Studio's connect-page snippet was corrected (§3)
  against current docs. Open WebUI (via its MCPO proxy) and llama.cpp's
  MCP client are not in `clients.ts` as guided rows yet and were not
  otherwise touched by this SPEC.
