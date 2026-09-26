# @byte5ai/palaia

**palaia memory backend for OpenClaw.**

Replace OpenClaw's built-in `memory-core` with palaia — local, cloud-free, WAL-backed agent memory with tier routing and semantic search.

## Installation

```bash
# Install palaia (Python CLI)
pip install palaia

# Install the OpenClaw plugin
openclaw plugins install @byte5ai/palaia
```

## Configuration

Activate the plugin by setting the memory slot in your OpenClaw config:

```json5
// openclaw.config.json5
{
  plugins: {
    slots: { memory: "palaia" }
  }
}
```

Restart the gateway after changing config:

```bash
openclaw gateway restart
```

Running OpenClaw's native Active Memory plugin as well? See
[OpenClaw Active Memory + palaia](../../docs/openclaw-active-memory.md) for how the two
arrangements differ and which one to pick.

### Plugin Options

All options are optional — sensible defaults are used:

```json5
{
  plugins: {
    config: {
      palaia: {
        binaryPath: "/path/to/palaia",  // default: auto-detect
        workspace: "/path/to/workspace", // default: agent workspace
        tier: "hot",                      // default: "hot" (hot|warm|all — see note below)
        maxResults: 10,                   // default: 10
        timeoutMs: 3000,                  // default: 3000
        memoryInject: true,               // default: true (inject HOT into context)
        maxInjectedChars: 4000,           // default: 4000
        captureOnCompaction: true,        // default: true (save a summary before compaction)
      }
    }
  }
}
```

**`tier`:** searches (`memory_search` and `recallMode: "query"`) only distinguish
`"all"` from everything else — `"all"` adds COLD entries, while `"hot"` and `"warm"`
both search HOT + WARM. List-based recall (`recallMode: "list"`, or the fallback whenever
query-based recall yields no entries — no match, a too-short message, or a query error)
uses the value as an exact tier filter.

## Agent Tools

### `memory_search` (always available)

Search palaia memory (semantic + keyword ranking). `maxResults` defaults to the
plugin's `maxResults` setting; pass `tier: "all"` to include COLD entries:

```
memory_search({ query: "deployment process", maxResults: 5, tier: "all" })
```

### `memory_get` (always available)

Read a specific memory entry:

```
memory_get({ path: "abc-123-uuid", from: 1, lines: 50 })
```

### `memory_write` (optional, opt-in)

Write new memory entries. Enable per-agent:

```json5
{
  agents: {
    list: [{
      id: "main",
      tools: { allow: ["memory_write"] }
    }]
  }
}
```

Then agents can write:

```
memory_write({ content: "Important finding", scope: "team", tags: ["project-x"] })
```

## Features

- **Zero breaking changes** — Drop-in replacement for `memory-core`
- **WAL-backed writes** — Crash-safe, recovers on startup
- **Tier routing** — HOT → WARM → COLD with automatic decay
- **Scope isolation** — private, team, shared:X, public
- **Hybrid search** — BM25 keyword + semantic embeddings, ranked together; BM25
  alone still works when no embedding provider is available, so no external API
  is required
- **HOT memory injection** — On by default: active memory is injected into agent
  context (`memoryInject: false` turns it off — note the [prompt-caching
  trade-off](../../docs/prompt-caching.md))
- **Capture before compaction** — On by default: right before OpenClaw compacts
  the conversation, palaia saves a session summary tagged `pre-compaction`, so
  what compaction drops stays searchable (`captureOnCompaction: false` turns it off)
- **Auto binary detection** — Finds `palaia` in PATH, pipx, or venv

## Architecture

```
OpenClaw Agent
  └─ @byte5ai/palaia (plugin)
       └─ palaia CLI (subprocess, --json)
            └─ .palaia/ (local storage)
                 ├─ hot/    (active memory)
                 ├─ warm/   (recent, less active)
                 ├─ cold/   (archived)
                 ├─ wal/    (write-ahead log)
                 └─ index/  (search index)
```

## Development

```bash
# Clone the repo
git clone https://github.com/byte5ai/palaia.git
cd palaia/packages/openclaw-plugin

# Install deps
npm install

# Run tests
npx vitest run
```

## License

MIT
