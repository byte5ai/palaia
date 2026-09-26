# Client-side packages

What palaia installs *into* an agent, as opposed to what the hub serves it.

Connecting a client gives an agent the memory's tools. It does not make the
agent use them: in the SPEC-207 baseline runs, an agent with the tools
connected and no skill loaded answered a task whose house answer was in the
memory without ever opening it, and acknowledged a decision in prose without
saving it. These packages are the fix, in the one format that is not
vendor-specific — [Agent Skills](https://agentskills.io) (`SKILL.md`), with
~40 adopters.

## Packages

| Package | For | Teaches |
|---|---|---|
| [`skills/palaia-memory`](skills/palaia-memory/SKILL.md) | the default | Both halves: recall before deciding, resume with `build_context`, which memory to use, and the capture discipline. |
| [`skills/palaia-capture`](skills/palaia-capture/SKILL.md) | constrained agents | Saving only — the 4-field contract and drop-and-move-on, nothing about looking things up. |
| [`skills/palaia-messenger`](skills/palaia-messenger/SKILL.md) | any agent working alongside others | Register on start, check before picking up a task, reply-or-decline, and keeping a message short with a reference instead of pasted content. See [`docs/messenger.md`](../docs/messenger.md) for the full contract. |
| [`skills/palaia-install`](skills/palaia-install/SKILL.md) | an assistant setting palaia up, before any hub exists | A guided, plain-language install: where it should live, the Tailscale key, the ready-to-paste cloud-config or the one-line installer, and reading `/var/log/cloud-init-output.log` when it does not come up. |

All four carry a `## Per-model notes` section, written with the vault
format's own variant markers (`[anthropic]`, `[openai]`, `[google]`) — the
same idea as per-model observation variants in a note, applied to skill
prose.

## Installing one

The dashboard's connect-a-client page offers these per client, with the
install path for that client and a copy/download of the file
(`v3/web/src/lib/skills.ts` holds the per-client gate; `palaia-install` is
not offered there, since that page belongs to a hub that is already
running). By hand, for Claude
Code:

```bash
mkdir -p ~/.claude/skills/palaia-memory
cp v3/clients/skills/palaia-memory/SKILL.md ~/.claude/skills/palaia-memory/
```

## The plugin wrapper

[`.claude-plugin/plugin.json`](.claude-plugin/plugin.json) makes this
directory a loadable plugin, so every skill under `skills/` installs as one
unit — the one plugin's `source` is this directory, and the lint below fails
any skill package that no listed plugin would ship:

```bash
claude --plugin-dir v3/clients      # this session only
```

[`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) is the
Claude Code plugin-marketplace manifest for these skills (the hub's own
add-on marketplace is the dashboard's Marketplace page). Both manifests
carry `v3/VERSION`'s version — `server/tests/test_version_drift.py` refuses
any other — and, with the skills' frontmatter, are linted in CI —
`server/tests/clients/test_skill_format.py`, or by hand:

```bash
cd v3 && uv run python server/tests/clients/skill_lint.py
```

`palaia-install` never restates an install command: it tells the assistant
to read `v3/deploy`'s real files and `v3/VERSION`, and
`server/tests/clients/test_install_skill_drift.py` checks that every path,
URL and command it does quote still matches what `v3/deploy` ships — and
runs the cloud-config key edit it prescribes against the real file.

## Effectiveness runs

Prose aimed at a model can only be verified by running a model. The harness in
`v3/server/tests/effectiveness/` gives the real `claude` CLI a task that never
mentions memory, over a real hub on the golden vault, and records which tool
calls actually happened. It is excluded from CI (real model calls) and gated:

```bash
cd v3 && PALAIA_EFFECTIVENESS=1 uv run pytest server/tests/effectiveness -s -v
```

Read `server/tests/effectiveness/harness.py` before changing a word of the
memory/capture skills, or `server/tests/effectiveness/messaging_harness.py`
before changing a word of the messenger skill — each explains its own
probes, the no-skill baseline they are compared against, and why the
evidence is collected server-side.
