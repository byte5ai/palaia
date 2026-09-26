# OpenClaw Active Memory + palaia

OpenClaw ships a native **Active Memory** plugin whose memory sub-agent pulls context
before the main reply. palaia is itself an OpenClaw memory plugin and does the same job
without spending a model call on retrieval. This chapter explains how the two fit
together, how to configure each arrangement, and where the integration stops.

> **Scope of what is verified here.** Everything stated about **palaia** is read off
> this repository and cited by file and line. Everything about **OpenClaw's own**
> `active-memory` plugin — its config keys, its tool allowlist, its version history —
> comes from [#194](https://github.com/byte5ai/palaia/issues/194) and is marked
> **UNVERIFIED**: `openclaw` is a peer dependency and is not vendored here, so this
> repository cannot confirm it. Check your host's own docs before relying on those
> parts.

## Which arrangement do you want?

| | **A — palaia in the memory slot** (recommended) | **B — Active Memory in front of palaia** |
|---|---|---|
| Who retrieves | palaia, on every prompt build | OpenClaw's memory sub-agent, calling palaia's tools |
| Model calls per retrieval | 0 | ≥ 1 (the sub-agent) |
| Verified in this repo | Yes — this is what the plugin ships | No — depends on an upstream option we cannot confirm |
| `palaia doctor` | reports "palaia is active" | reports "*other* is active (not palaia)", see [Gotchas](#limits-and-gotchas) |

Use **A** unless you specifically want OpenClaw's sub-agent to stay in charge of
*deciding* what to recall.

## How OpenClaw finds palaia

Three facts drive every snippet below; all three are what palaia's own `doctor` reads.

- **Config file.** `~/.openclaw/openclaw.json`, or the same basename as `.yaml`/`.yml`,
  or `config.json`/`.yaml`/`.yml` in that directory; `$OPENCLAW_CONFIG` overrides the
  search (`palaia/doctor/checks.py:234-252`).
- **Activation** is a slot: `plugins.slots.memory` (`checks.py:274-279`,
  `packages/openclaw-plugin/index.ts:23`).
- **Plugin options** live at `plugins.entries.<pluginId>.config`
  (`checks.py:1352-1354`, `index.ts:38-41`). Older copies of the plugin README use the
  spelling `plugins.config.palaia`; the path the code actually reads is the one above.

palaia registers three agent tools (`packages/openclaw-plugin/src/tools.ts`):

| Tool | Availability | Parameters |
|---|---|---|
| `memory_search` | always (`tools.ts:162`) | `query`, `maxResults`, `tier`, `type` |
| `memory_get` | always (`tools.ts:258`) | `path`, `from`, `lines` |
| `memory_write` | opt-in — registered with `{ optional: true }` (`tools.ts:296,405`), so each agent must allow it | `content`, `scope`, `tags`, `type`, `project`, `title`, `force` |

**There is no tool named `palaia`, and none named `palaia query`.** `palaia query` is a
CLI command ([CLI reference](cli-reference.md#palaia-query)) that `memory_search` shells
out to internally (`tools.ts:103-110`). Anywhere a host config wants *tool names*, the
values are `memory_search` and `memory_get`.

## Setup A — palaia as the memory backend

```json
{
  "plugins": {
    "slots": { "memory": "palaia" },
    "entries": {
      "palaia": {
        "config": {
          "tier": "hot",
          "maxResults": 10,
          "timeoutMs": 3000,
          "memoryInject": true
        }
      }
    }
  },
  "agents": {
    "list": [
      { "id": "main", "tools": { "allow": ["memory_write"] } }
    ]
  }
}
```

Those four values are the defaults (`packages/openclaw-plugin/src/config.ts:87-92`) and
are shown only to make the shape explicit — omit any of them. The full key list is in
[Configuration → OpenClaw Plugin Configuration](configuration.md#openclaw-plugin-configuration).

```bash
openclaw gateway restart
palaia doctor          # expects: "OpenClaw plugin — palaia is active"
```

This *is* the Active Memory integration, not a replacement for it. palaia registers
exactly the tool names the host's memory prompt looks for — the ContextEngine checks
`availableTools.has("memory_search")` before adding guidance
(`src/context-engine.ts:479`) — and contributes its own prompt lines through
`registerMemoryCapability("palaia", { promptBuilder })` (`index.ts:74-78`), falling back
to the deprecated `registerMemoryPromptSection` on older hosts. The agent's habit of
reaching for memory is unchanged; what answers underneath becomes palaia.

## Setup B — Active Memory with palaia as its search backend

The idea: leave OpenClaw's `active-memory` plugin in the memory slot and restrict its
sub-agent to palaia's tools, so the sub-agent still decides *when* to recall while
palaia decides *what matches*.

```json
{
  "plugins": {
    "slots": { "memory": "active-memory" },
    "entries": {
      "active-memory": {
        "config": { "toolsAllow": ["memory_search", "memory_get"] }
      },
      "palaia": {
        "config": { "timeoutMs": 5000, "memoryInject": false }
      }
    }
  }
}
```

**Verify two things before relying on this.** Neither can be checked from this
repository:

1. That `active-memory` accepts a `toolsAllow` option under
   `plugins.entries.active-memory.config` at all, and that it takes *tool names*.
   Check `openclaw plugins info active-memory` or your host's docs. If the option does
   not exist, there is no way to redirect the sub-agent — use Setup A.
2. That your host still loads palaia's tools while another plugin occupies the memory
   slot. Slot occupancy and plugin loading are host behaviour; the plugin itself
   registers its tools unconditionally in `register()` (`index.ts:54-55`), but whether
   OpenClaw calls `register()` for a non-slotted memory plugin is an upstream question.

`memoryInject: false` is set above deliberately — see [Two injectors](#limits-and-gotchas).

### Timeouts

`timeoutMs` (default `3000`) bounds the **embed-server socket query** only
(`tools.ts:94`). When that path is unavailable, `memory_search` falls back to a
`palaia query … --json` subprocess with a **hard-coded 15 s timeout** that no config key
changes (`tools.ts:70`). So raising `timeoutMs` buys headroom on the fast path — useful
on a cold index — and does nothing for the fallback. Keep the embed server on
(`embeddingServer: true`, the default) instead; see [Embedding server](embed-server.md).

## What palaia adds over a plain memory search

Through the tool, the sub-agent gains tier and entry-class filters that a flat
memory store has no equivalent for (`tools.ts:166-181`):

```js
// only SOPs and processes, across hot and warm
memory_search({ query: "deployment", type: "process", maxResults: 5 })
// include archived entries
memory_search({ query: "postgres migration", tier: "all" })
```

Beyond the tool, the CLI filters on structure — project, task status, priority,
assignee, tags, time windows ([CLI reference](cli-reference.md#palaia-query)):

```bash
palaia query "deploy" --project checkout --type task --status open --after 2026-09-01
```

**Be aware of the gap:** `memory_search` exposes only `query`, `maxResults`, `tier` and
`type`. `--project`, `--status`, `--tags` and the date windows are **not** reachable
from the tool. An agent that needs them has to run the CLI through a shell tool. Per-agent
and per-project injection behaviour is tuned separately through
`palaia priorities` ([CLI reference](cli-reference.md#palaia-priorities)), which also
simulates what a given query would inject.

## Limits and gotchas

- **Two injectors, two blocks.** palaia injects a section headed
  `## Active Memory (palaia)` (`src/hooks/index.ts:491`, `src/context-engine.ts:182`).
  OpenClaw's Active Memory injects its own. There is no negotiation seam between them —
  the mirrored plugin SDK carries a prompt builder and a public-artifact list, neither of
  which exposes what the host retrieved ([#194](https://github.com/byte5ai/palaia/issues/194)).
  Turn one side off deliberately: `memoryInject: false` for palaia.
- **Re-capture loop.** palaia detects injected recall context that got captured back into
  the store (`palaia/doctor/checks.py:512-534`, matching on the block heading). A second
  injecting system raises that risk; run `palaia doctor` after switching arrangements.
- **Doctor output changes in Setup B.** With another plugin in the memory slot, the
  plugin check reports `"<plugin> is active (not palaia)"` (`checks.py:287-300`) and the
  capture-model check skips entirely, because it only proceeds when
  `plugins.slots.memory == "palaia"` (`checks.py:1348-1349`). Expected, not a fault.
- **Scope isolation follows `PALAIA_AGENT`.** `memory_search` resolves scope visibility
  from the `PALAIA_AGENT` environment variable (`tools.ts:195`), not from the calling
  agent's id. If a memory sub-agent runs under a different identity and you rely on
  `private` scopes, verify what `PALAIA_AGENT` is set to in that process. See
  [Multi-agent](multi-agent.md).
- **Retrieval is free; capture is not.** palaia's retrieval spends no model call — the
  query is built from the transcript with string operations, ranking is arithmetic.
  Auto-*capture* does call a model (`captureModel`, with a rule-based fallback). A memory
  sub-agent, by contrast, spends a model call per retrieval.

## To verify against your OpenClaw version

1. Does `active-memory` exist as an installable plugin, and does it take a tool
   allowlist under `plugins.entries.active-memory.config`?
2. Is the key spelled `toolsAllow`, and does it hold tool names?
3. Are a non-slotted memory plugin's tools still registered?
4. Is there a host signal that Active Memory is active, so palaia could suppress its own
   block automatically rather than by config?

If you confirm any of these, please report it on
[#198](https://github.com/byte5ai/palaia/issues/198) so this chapter can drop the
UNVERIFIED markers.
