<!-- graphic: hero banner (logo/wordmark + tagline), light + dark, SVG preferred (issue #298 item 1). Goes directly above the <h1>. -->

<div align="center">

<pre>
             .__         .__        
___________  |  | _____  |__|____   
\____ \__  \ |  | \__  \ |  \__  \  
|  |_> > __ \|  |__/ __ \|  |/ __ \_
|   __(____  /____(____  /__(____  /
|__|       \/          \/        \/ 
</pre>

# Your AI tools finally share one memory.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/byte5ai/palaia?include_prereleases&label=release)](https://github.com/byte5ai/palaia/releases)
[![v3 CI](https://github.com/byte5ai/palaia/actions/workflows/v3-ci.yml/badge.svg)](https://github.com/byte5ai/palaia/actions/workflows/v3-ci.yml)
[![Container image](https://img.shields.io/badge/image-ghcr.io%2Fbyte5ai%2Fpalaia--hub-blue?logo=docker&logoColor=white)](v3/deploy/README.md)

[Get started](#get-started-in-60-seconds) · [What it does](#what-it-does-for-you) · [Docs](v3/site/docs/src/content/docs/index.md) · [How it works](v3/docs/how-it-works.md) · [Coming from v2?](v3/docs/migrate-from-v2.md)

</div>

<!-- graphic: 30-second demo GIF (issue #298 item 2): the install command, the setup wizard, a memory saved from one AI tool and recalled from another. Goes here, before the first paragraph. -->

palaia is a hub you run yourself: on a server in your office, in your own cloud
account, or on a machine at home. Every AI tool you use connects to it
once: Claude, ChatGPT, Codex, Gemini, and any other tool that speaks MCP, the open
standard AI tools use to reach outside data and tools. From then on they share one
memory and one set of tools, and they can hand work to each other. Your data stays in
plain files on hardware you control.

Think Home Assistant, for your AI tools.

> [!NOTE]
> **palaia v3 is a release candidate (`3.0.0-rc1`).** Everything below works and is
> tested, but it has not had an outside security review yet. Try it, keep backups, and
> [tell us what breaks](https://github.com/byte5ai/palaia/issues). If you are running
> palaia v2 today, it stays [supported](#already-using-palaia-v2).

## What it does for you

- **Your AI tools remember, together.** Tell one assistant about a decision and the
  others know it too. Your memory is a folder of plain Markdown notes you can open in
  any editor (Obsidian opens it as-is), search, and back up like any other files.
- **Set up a tool once, use it everywhere.** Install an add-on in palaia and every
  connected AI can use it. No more pasting the same configuration into five apps.
- **Your agents can work as a team.** An AI session on your laptop can hand a task
  to one on your server, with the context attached, and find out who is already
  working on what.
- **Runs where you decide.** A server in your office, a machine in your cloud account,
  a NAS, or a Raspberry Pi. No account with us, no subscription, no data leaving your
  infrastructure unless you say so.
- **Safe by default.** Sign in with GitHub or Google, pick in the setup wizard how far
  your hub should reach (just this machine, your private network, or the internet),
  and back everything up with one click.

## Get started in 60 seconds

You need [Docker](https://docs.docker.com/get-started/get-docker/). That is the whole
prerequisite list.

```bash
docker run -d --name palaia-hub \
  -p 8420:8420 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:beta
```

Then open **`http://<your-machine>:8420`** in a browser (on many home networks
`http://palaia.local` works too). A short setup wizard takes it from there: sign in,
save your first memory, connect your first AI tool. No config files, no second
command.

Once `3.0.0` is final, use `:stable` instead of `:beta`. Updating later is one click
in the dashboard.

**Other ways to install**

| You have… | Do this |
|---|---|
| A Synology NAS | Paste one file into Container Manager, no terminal: [step-by-step guide](v3/site/docs/src/content/docs/install-synology.md) |
| A Raspberry Pi | The command above works on 64-bit Raspberry Pi OS with Docker. A ready-to-flash card image is [in progress](v3/deploy/pi-image/) |
| A rented server (Hetzner, DigitalOcean, AWS, …) | Paste [`cloud-init.yaml`](v3/deploy/cloud-init.yaml) into your provider's user-data field. It installs everything and keeps the hub off the open internet |
| Umbrel, CasaOS, Runtipi, TrueNAS SCALE | [Packages are ready](v3/deploy/stores/); until they are in the official catalogs, use the command above |
| Docker Compose or Portainer | [`docker-compose.yml`](v3/deploy/docker-compose.yml) |

<!-- rc-channel-note -->
> **Release candidate:** the files and packages in this table pin `ghcr.io/byte5ai/palaia-hub:stable`,
> which does not exist until `3.0.0` is final. Until then, change `:stable` to `:beta` in whatever you use.

Stuck? See [Your first shared memory](v3/site/docs/src/content/docs/first-shared-memory.md)
for a walkthrough with screenshots, or [troubleshooting](v3/site/docs/src/content/docs/troubleshooting.md).

## Works with

Claude Code · Claude Desktop · claude.ai · ChatGPT · Codex · Gemini CLI · Grok ·
LM Studio · any other MCP-compatible tool

Each one has a short [connect guide](v3/site/docs/src/content/docs/connect/clients/).
Claude Desktop gets a one-click bundle: download, click, connected.

<!-- graphic: dashboard screenshots (issue #298 item 4): home screen, memory explorer, connect page, marketplace. One row of four goes here. -->

## Learn more

- **[Documentation](v3/site/docs/src/content/docs/index.md):** getting started, connecting each tool, backup and restore, troubleshooting.
- **[How it works](v3/docs/how-it-works.md):** the full feature list, the architecture, the test evidence behind the claims, and when palaia is not the right fit.
- **[Security](v3/SECURITY.md)** and the [threat model](v3/docs/security/threat-model.md).
- **[What is left before 3.0.0](v3/RELEASING.md)** and [what shipped](v3/CHANGELOG.md).
- **For contributors:** [`CONTRIBUTING.md`](CONTRIBUTING.md), [`AGENTS.md`](AGENTS.md), and [`v3/README.md`](v3/README.md) for the dev setup.

## Already using palaia v2?

palaia v2 is the Python package at the root of this repository. It stays installable
and supported with critical fixes; its [documentation](docs/getting-started.md) is
unchanged. Nobody is being pushed off it. When you are ready, one command imports
your v2 knowledge into v3, and the [migration guide](v3/docs/migrate-from-v2.md)
covers what changes and how to roll back.

## Community & support

- **Questions, bugs, ideas:** [open an issue](https://github.com/byte5ai/palaia/issues).
- **Security vulnerabilities:** please do not open a public issue. Use GitHub's
  [private vulnerability reporting](https://github.com/byte5ai/palaia/security/advisories/new)
  instead. Details in [`v3/SECURITY.md`](v3/SECURITY.md).

## License

[MIT](LICENSE) · © 2026 [byte5 GmbH](https://byte5.de)
