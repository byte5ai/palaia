# MCP Server

palaia includes an MCP memory server that works with any MCP-compatible host. Claude Code uses it via `palaia setup claude-code` (see [Claude Code docs](claude-code.md)). For Claude Desktop, Cursor, and other MCP hosts, add the config manually as described below.

## Installation

```bash
pip install "palaia[mcp,fastembed]"
palaia init
palaia doctor --fix
```

## Configuration

### Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

With explicit store path:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp",
      "args": ["--root", "/path/to/.palaia"]
    }
  }
}
```

### Cursor

Settings → MCP Servers → Add:
- **Command**: `palaia-mcp`
- **Arguments**: (none, or `--root /path/to/.palaia`)

Or add to `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

### Claude Code

The easiest way to set up Claude Code is the automated setup command:

```bash
palaia setup claude-code --global
```

This configures `~/.claude/settings.json` and generates a CLAUDE.md with agent instructions. Restart Claude Code after setup.

See [Claude Code Integration](claude-code.md) for the full guide, including the paste-this prompt for fully autonomous setup.

For manual configuration, add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp"
    }
  }
}
```

### Other MCP Hosts

Any MCP-compatible host that supports stdio transport can use palaia:
```bash
palaia-mcp                              # stdio transport (default)
palaia-mcp --root /path/to/.palaia      # explicit store
palaia-mcp --read-only                  # no writes
```

## Available Tools

| Tool | Purpose | Read-only |
|------|---------|-----------|
| `palaia_search` | Semantic + keyword search across memories | Available |
| `palaia_read` | Read a specific entry by ID (full or short prefix) | Available |
| `palaia_list` | List entries by tier, type, or project | Available |
| `palaia_status` | Store health: entry counts, provider info, backend | Available |
| `palaia_store` | Save a new memory (fact, process, task) | Blocked |
| `palaia_edit` | Update an existing entry | Blocked |
| `palaia_gc` | Run garbage collection (tier rotation) | Blocked |

### palaia_search

Find relevant memories by meaning:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `query` | Yes | Search text |
| `limit` | No | Max results (default: 10) |
| `project` | No | Filter by project |
| `entry_type` | No | Filter: memory, process, task |
| `status` | No | Filter: open, in-progress, done, wontfix |
| `priority` | No | Filter: critical, high, medium, low |
| `assignee` | No | Filter by assignee |
| `include_cold` | No | Include archived entries |
| `cross_project` | No | Search across all projects |

### palaia_store

Save knowledge that should persist:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `content` | Yes | Memory content |
| `title` | No | Short title |
| `tags` | No | List of tags |
| `entry_type` | No | memory (default), process, task |
| `scope` | No | team (default), private, public |
| `project` | No | Project name |
| `agent` | No | Owning agent (default: the server's agent identity, see below) |
| `status` | No | Task status |
| `priority` | No | Task priority |

### palaia_read

Read a single entry:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entry_id` | Yes | Full UUID or short prefix (8+ chars) |

### palaia_edit

Update an existing entry (only provided fields change):

| Parameter | Required | Description |
|-----------|----------|-------------|
| `entry_id` | Yes | Entry to edit |
| `content` | No | New content |
| `title` | No | New title |
| `tags` | No | New tags (replaces) |
| `status` | No | New status |
| `priority` | No | New priority |
| `assignee` | No | New assignee |

### palaia_gc

Run garbage collection:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `dry_run` | No | Preview only (default: true) |

## Read-Only Mode

```bash
palaia-mcp --read-only
```

Disables `palaia_store`, `palaia_edit`, and `palaia_gc`. Use this when connecting untrusted AI tools that should read memories but not modify them.

## Store Discovery

The MCP server finds the `.palaia` store using the same logic as the CLI:

1. `--root` argument (explicit)
2. `PALAIA_HOME` environment variable
3. Walk up from current directory looking for `.palaia/`
4. `~/.palaia` (home directory)
5. `~/.openclaw/workspace/.palaia` (OpenClaw default)

If no store is found, the server exits with an error message suggesting `palaia init`.

## Agent Identity

The server acts as one agent, resolved once at startup exactly like the CLI resolves it
without `--agent`, so the CLI and the MCP server act as the same agent on a store:

- **multi-agent store** (`multi_agent: true`): `PALAIA_AGENT`, then `agent` in `config.json`,
  then the detected OpenClaw agent, then `default`
- **single-agent store**: `agent` in `config.json`, then the detected agent (`PALAIA_AGENT` or
  OpenClaw), then `default`

All tools use this identity for scope checks. The agent can read, search, list and edit its own
`private` entries. Other agents' private entries behave like missing entries: `palaia_read` and
`palaia_edit` answer "Entry not found", and list and search don't show them.

`palaia_store` records the identity as the entry's owner. The `agent` parameter can name a
different owner for non-private entries only, because the server could not read or edit a private
entry it doesn't own. In a multi-agent store without an identity (the `default` fallback),
`palaia_store` refuses private entries, whether the scope is explicit or comes from a project or
global default, just as `palaia write` does.

To run one server per agent against a shared multi-agent store, set the identity in the host
config:
```json
{
  "mcpServers": {
    "palaia": {
      "command": "palaia-mcp",
      "env": { "PALAIA_AGENT": "my-agent" }
    }
  }
}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "MCP SDK not installed" | `pip install 'palaia[mcp]'` |
| "No .palaia store found" | Run `palaia init` first, or use `--root` |
| Tool calls are slow | Install sqlite-vec: `pip install 'palaia[sqlite-vec]'` |
| No semantic results | Check `palaia detect` for embedding provider |
| Permission errors | Check file permissions on `.palaia/` directory |
