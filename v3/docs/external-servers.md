# External MCP servers and the secret store (SPEC-302)

> One endpoint, many tools (MASTERPLAN §5.2). Connect somebody else's MCP
> server to palaia once, and it appears — named, renamable, health-checked —
> on whichever profiles you put it on. Its API key lives in palaia's
> encrypted store, not in every client's config file.

## What a connected server is

An entry under `gateway.upstreams` in `config.yaml`, of one of two kinds:

| Kind | What it is | What palaia does |
|---|---|---|
| `http` | A server on the internet (or your network) speaking streamable HTTP | Connects to its URL, adding a header from the secret store if you configured one |
| `stdio` | A program on this machine | Starts it, talks over its pipes, injects the secrets you named into its environment, and stops it when the hub stops |

Listing a server connects it. Listing it in a **profile's** `upstreams` is
what exposes its tools to the clients using that profile — the two steps are
separate on purpose, so connecting something does not hand it to everything.

Its tools appear as `<namespace>_<tool>` (default namespace: the server's
key), and any of them can be renamed. Renames are stored **pre-namespace** —
you write the part after the prefix, palaia composes the rest (the reason is
FINDINGS Q4 in `v3/spikes/gateway/FINDINGS.md`: fastmcp applies a rename
before adding the prefix, so storing the full displayed name double-prefixes
it).

The profile's own instructions carry one line per connected server —
*"tools named `linear_*` come from Linear — an outside service, connected by
you"* — so a model reading the tool surface can tell palaia's own memory
tools apart from a third party's. The servers' own tool descriptions pass
through unchanged; palaia does not rewrite or vouch for them.

## Credentials: what goes where

**Nothing secret goes in `config.yaml`.** An entry names the secret it
needs; the value lives encrypted in the store.

```yaml
gateway:
  upstreams:
    - key: linear
      kind: http
      display_name: Linear
      url: https://mcp.linear.app/mcp
      auth:
        header: Authorization          # default
        value_template: "Bearer {secret}"   # default
        secret_name: linear-token      # ← a name, never a value
    - key: weather
      kind: stdio
      display_name: Weather box
      command: /usr/local/bin/weather-mcp
      args: ["--stdio"]
      env_secrets:
        WEATHER_API_KEY: weather-key   # ← env var: secret name
```

For an API key in a custom header, set `header: X-API-Key` and
`value_template: "{secret}"`.

The header palaia sends an `http` server is **only** the one its `auth:`
names: the connecting client's own credential (its palaia `plt_` token or
OAuth JWT) and its other request headers are never forwarded to an external
server, with or without an `auth:` block (issue #314 — fastmcp's proxy
forwards them by default; palaia switches that off).

### The store

- `<home>/secrets.sqlite3` — values encrypted with Fernet, file mode `0600`.
- `<home>/secrets.key` — the encryption key, `0600`, inside the `0700` home,
  created with `O_CREAT | O_EXCL` and never overwritten. Both are re-narrowed
  every time the hub opens them, so a file widened by a `chmod` or an
  `rsync -a` from a laxer machine is quietly fixed.
- Copying the database without its key makes every value unreadable — by
  design. palaia says so by name (*"secret `linear-token` cannot be decrypted
  with the current secrets.key"*) rather than failing vaguely.

### Write-only, by construction

| Route | Does |
|---|---|
| `PUT /api/secrets/{name}` | Stores a value (replacing any previous one) |
| `GET /api/secrets` | Lists **names and timestamps** |
| `DELETE /api/secrets/{name}` | Removes one |

There is no route that returns a value, and no response model in the hub has
a field one could be placed in. A value is decrypted only inside the hub
process, at the moment a header or a child process's environment is built. It
is never logged, never included in an error message, and never part of an
event payload — asserted by
`server/tests/upstream/test_secret_never_leaks.py`.

### OAuth against a third party: what this is not

palaia does **not** run an OAuth login flow against somebody else's
authorization server. If a service issues you a token, paste it into the
secret store and reference it by name. That is the whole v1 path, stated
plainly rather than implied away. (palaia's *own* OAuth server — the one your
clients log into to reach palaia — is a different thing entirely; see
SPEC-203.)

## Health

Each server is probed (connect → initialize → `tools/list`) on a bounded
timeout, on a background pass roughly every minute, and on demand via
`POST /api/gateway/upstreams/{key}/probe`. `GET /api/gateway/upstreams`
reports every server with one plain-language status line.

What happens when one is unreachable:

- Its tools are **absent** from the profiles that mount it. Everything else
  on those profiles keeps working exactly as before.
- Nothing waits on it. Hub startup never probes (so a dead server cannot
  delay a start), and a profile never holds a mount that would time out on
  every `tools/list`.
- It comes back on its own: the pass that finds it reachable again rebuilds
  the profiles that mount it, with no restart and nothing to click.
- `gateway.upstream.up` / `gateway.upstream.down` fire **only on a change**,
  so a healthy server is silent. See [events.md](events.md) §3.4.

## Two fences

**The curator never mounts an external server.** It runs a model over your
own notes; an outside tool inside that session could carry them out. The
refusal is in three places — the profile schema will not hold it, the builder
will not mount it, and the REST route will not accept it — because one of
them is not enough (`server/tests/upstream/test_curator_fence.py`).

**Name collisions are refused, loudly, at config time.** Two servers cannot
claim one tool prefix, and no server can claim a vault's (`work_memory`) —
that would silently shadow your memory tools. The error names both claimants
and the fix. A switched-off server still owns its prefix, so turning it back
on later cannot surprise you.
