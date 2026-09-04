/**
 * The client integration catalog (SPEC-110), read straight off
 * MASTERPLAN.md §6's client integration matrix — every entry there gets a
 * row here, so "every §6-matrix client has a connect flow" (this SPEC's
 * acceptance criterion) is checkable by diffing this array against that
 * table, not by memory.
 *
 * Three kinds of entry:
 * - `guided`: the client connects to *this device* (a local process, or a
 *   custom MCP config it owns) — always reachable, in every operating
 *   mode, because nothing outside the operator's own network is involved.
 *   These get the real, working flow: `ConnectPanel` issues a token
 *   through the already-built `/api/auth/tokens` (SPEC-108) and shows the
 *   copy-command / paste-prompt pair, plus a "download the file" one-click
 *   for clients whose real install path is "put this file there"
 *   (SPEC-306 deliverable #3 — `configFile`).
 * - `download`: Claude Desktop (SPEC-306) — a signed bundle assembled
 *   fresh per click by `/api/connect/mcpb`, with the hub's address and a
 *   credential already filled in, so it is a genuine one-click install
 *   rather than a copy/paste.
 * - `notYet`: the client connects *from the vendor's cloud* (claude.ai,
 *   ChatGPT, Grok). `notYetReason(mode)` returns the truthful, mode-aware
 *   explanation this SPEC's acceptance criterion asks for — never a dead
 *   end, always why and what changes it.
 */
import type { ComponentType, SVGProps } from "react";

import {
  ClientsIcon,
  ExplorerIcon,
  LinkIcon,
  SparkleIcon,
  ToolsIcon,
} from "../shell/icons";

export type HubMode = "locked" | "cloud" | "open";

export interface ConfigFile {
  filename: string;
  content: string;
  mimeType: string;
}

/**
 * Issue 318: every mounted profile requires the per-client token
 * (`auth_enabled` defaults to true in every mode; a tokenless call gets a
 * 401), so every snippet below carries it — in each client's own
 * mechanism, verified against `v3/docs/client-matrix-results.md` where
 * that document has evidence. `token` is the plaintext `ConnectPanel`
 * just minted; when it is not known (the docs generator, or a panel
 * revisited after the one-time display) this placeholder stands in, so
 * a tokenless command is never rendered as if it would work.
 */
export const TOKEN_PLACEHOLDER = "<paste-your-token>";

/** The environment variable Codex reads the token from (`bearer_token_env_var`). */
export const CODEX_TOKEN_ENV = "PALAIA_TOKEN";

export interface GuidedClient {
  kind: "guided";
  id: string;
  name: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  estimate: string;
  /** The one-liner for the "copy the command" tab. */
  command: (origin: string, profile: string, token?: string) => string;
  /** The self-configuring prompt for the "paste a prompt" tab. */
  prompt: (origin: string, profile: string, token?: string) => string;
  /** SPEC-306 deliverable #3: a one-click "download config file" — the
   * client's own real config-file format (SPEC-209-corrected), computed
   * client-side (no hub round-trip: it is just the origin, profile and
   * token, templated). Present only on clients whose real install path is
   * "put this file there" rather than "run this command". */
  configFile?: (origin: string, profile: string, token?: string) => ConfigFile;
}

export interface DownloadClient {
  kind: "download";
  id: string;
  name: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  subtitle: string;
  /** ``/api/connect/mcpb`` (SPEC-306 deliverable #4) — the hub assembles
   * and signs a bundle personalized for ``profile`` on every request; this
   * just names where. */
  downloadUrl: (origin: string, profile: string) => string;
}

export interface NotYetClient {
  kind: "notYet";
  id: string;
  name: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  subtitle: string;
  /** Truthful, mode-aware explanation — never just "not available". */
  reason: (mode: HubMode) => string;
  /** SPEC-205 deliverable #3: once Cloud/Open mode has sign-in actually
   * turned on and configured (the Access mode page), a cloud connector
   * unlocks here instead of staying stuck on `reason` above — the address
   * to paste into the client's own "custom connector" settings. Present
   * only on clients that connect through sign-in rather than through
   * this hub's own per-client tokens (claude.ai, ChatGPT, Grok). */
  oauthConnect?: (issuer: string, profile: string) => { url: string; note: string };
}

export type ClientEntry = GuidedClient | NotYetClient | DownloadClient;

const CLOUD_CONNECTOR_REASON = (name: string, planNote: string) => (mode: HubMode): string =>
  mode === "locked"
    ? `${name} connects from its own cloud, not from this device — Locked mode only answers ` +
      `inside your network, so it would time out whatever you paste into it. Switch to Cloud or ` +
      `Open mode to expose an endpoint it can reach.`
    : `${name} needs sign-in turned on for this hub, and it is not yet — turn it on from the ` +
      `Access mode page (Cloud and Open both support it), then come back here. ${planNote}`;

const OAUTH_CONNECT = (name: string) => (issuer: string, profile: string) => ({
  url: `${issuer.replace(/\/$/, "")}/mcp/${profile}`,
  note:
    `Paste this address into ${name}'s custom connector settings, then sign in with your ` +
    `palaia account when it asks.`,
});

const tokenOr = (token?: string): string => token ?? TOKEN_PLACEHOLDER;

/** The `Authorization` header value every HTTP client sends. */
const authHeader = (token?: string): string => `Bearer ${tokenOr(token)}`;

/** The shared "paste a prompt" text: the address, the header the hub
 * requires, and the one thing to do afterwards. */
const connectPrompt = (origin: string, profile: string, token?: string): string =>
  `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
  `Send the header "Authorization: ${authHeader(token)}" with every request.\n` +
  `Then run a test recall and tell me what you found.`;

export const CLIENTS: ClientEntry[] = [
  {
    kind: "guided",
    id: "claude-code-cli",
    name: "Claude Code CLI",
    icon: SparkleIcon,
    estimate: "one command · 1 min",
    // The literal command client-matrix-results.md §2.1/§7.2 ran against a
    // real hub: `--header` is how the CLI attaches the token.
    command: (origin, profile, token) =>
      `claude mcp add --transport http palaia ${origin}/mcp/${profile} ` +
      `--header "Authorization: ${authHeader(token)}"`,
    prompt: connectPrompt,
  },
  {
    kind: "guided",
    id: "codex",
    name: "Codex",
    icon: ToolsIcon,
    estimate: "one command · 1 min",
    // Codex never takes the token itself — only the name of an environment
    // variable holding it (`codex mcp add <name> --url <url>
    // --bearer-token-env-var VAR`, client-matrix-results.md §3), so the
    // export comes first and has to be in place whenever Codex starts.
    command: (origin, profile, token) =>
      `export ${CODEX_TOKEN_ENV}=${tokenOr(token)}\n` +
      `codex mcp add palaia --url ${origin}/mcp/${profile} --bearer-token-env-var ${CODEX_TOKEN_ENV}`,
    prompt: connectPrompt,
    // ~/.codex/config.toml's `[mcp_servers.*]` table (research/mcp-landscape-2026.md
    // §6) — streamable HTTP; `bearer_token_env_var` names the variable the
    // token is read from, the same one the command above exports.
    configFile: (origin, profile, token) => ({
      filename: "palaia-codex-mcp.toml",
      mimeType: "text/plain",
      content:
        `# Paste this into ~/.codex/config.toml (or merge it into an existing\n` +
        `# [mcp_servers] table).\n` +
        `[mcp_servers.palaia]\n` +
        `url = "${origin}/mcp/${profile}"\n` +
        `bearer_token_env_var = "${CODEX_TOKEN_ENV}"\n` +
        `# Codex reads the token from that variable — set it where Codex starts:\n` +
        `#   export ${CODEX_TOKEN_ENV}=${tokenOr(token)}\n`,
    }),
  },
  {
    kind: "download",
    id: "claude-desktop",
    name: "Claude Code (Desktop app)",
    icon: ExplorerIcon,
    subtitle: "One-click download — a signed bridge to your hub, no typing required",
    downloadUrl: (origin, profile) =>
      `${origin}/api/connect/mcpb?profile=${encodeURIComponent(profile)}&client_name=${encodeURIComponent(
        "Claude Code (Desktop app)",
      )}`,
  },
  {
    kind: "notYet",
    id: "claude-ai",
    name: "claude.ai",
    icon: LinkIcon,
    subtitle: "Web, desktop, mobile and Cowork — custom connector on every plan",
    reason: CLOUD_CONNECTOR_REASON(
      "claude.ai",
      "Every plan (including Free) can add palaia as a custom connector.",
    ),
    oauthConnect: OAUTH_CONNECT("claude.ai"),
  },
  {
    kind: "notYet",
    id: "chatgpt",
    name: "ChatGPT",
    icon: LinkIcon,
    subtitle: "Developer mode / custom connectors",
    reason: CLOUD_CONNECTOR_REASON(
      "ChatGPT",
      "Write access needs a Business, Enterprise or Edu workspace — Plus/Pro get a read-only " +
        "profile so recall still works.",
    ),
    oauthConnect: OAUTH_CONNECT("ChatGPT"),
  },
  {
    kind: "guided",
    id: "gemini-cli",
    name: "Antigravity / Gemini CLI",
    icon: ClientsIcon,
    estimate: "one command · 1 min",
    // `mcpServers.*.headers` is Gemini CLI's documented way to attach a
    // header to an `httpUrl` server (client-matrix-results.md §3 confirmed
    // the `httpUrl` shape against geminicli.com/docs/tools/mcp-server).
    command: (origin, profile, token) =>
      `# add to ~/.gemini/settings.json under "mcpServers"\n` +
      `{"palaia": {"httpUrl": "${origin}/mcp/${profile}", ` +
      `"headers": {"Authorization": "${authHeader(token)}"}}}`,
    prompt: connectPrompt,
    // A real, complete ~/.gemini/settings.json — not just the snippet to
    // merge in, since a settings.json with only this key is itself valid.
    configFile: (origin, profile, token) => ({
      filename: "palaia-gemini-settings.json",
      mimeType: "application/json",
      content: `${JSON.stringify(
        {
          mcpServers: {
            palaia: {
              httpUrl: `${origin}/mcp/${profile}`,
              headers: { Authorization: authHeader(token) },
            },
          },
        },
        null,
        2,
      )}\n`,
    }),
  },
  {
    kind: "notYet",
    id: "grok",
    name: "Grok",
    icon: ClientsIcon,
    subtitle: "Custom (bring-your-own) MCP connectors — web/iOS/Android",
    reason: CLOUD_CONNECTOR_REASON("Grok", "Connect from web, iOS or Android once it is on."),
    oauthConnect: OAUTH_CONNECT("Grok"),
  },
  {
    kind: "guided",
    id: "lm-studio",
    name: "LM Studio",
    icon: ToolsIcon,
    estimate: "one command · 1 min",
    // mcp.json's per-server `headers` object (lmstudio.ai/docs/app/mcp —
    // the same page client-matrix-results.md §3 corrected the shape against).
    command: (origin, profile, token) =>
      `# LM Studio → Program → mcp.json\n` +
      `{"mcpServers": {"palaia": {"type": "streamable-http", "url": "${origin}/mcp/${profile}", ` +
      `"headers": {"Authorization": "${authHeader(token)}"}}}}`,
    prompt: connectPrompt,
    configFile: (origin, profile, token) => ({
      filename: "palaia-lmstudio-mcp.json",
      mimeType: "application/json",
      content: `${JSON.stringify(
        {
          mcpServers: {
            palaia: {
              type: "streamable-http",
              url: `${origin}/mcp/${profile}`,
              headers: { Authorization: authHeader(token) },
            },
          },
        },
        null,
        2,
      )}\n`,
    }),
  },
  {
    kind: "guided",
    id: "generic",
    name: "Any other AI tool",
    icon: ExplorerIcon,
    estimate: "endpoint and token",
    // No vendor syntax to follow here: the address, and the one header
    // every request to it must carry.
    command: (origin, profile, token) =>
      `${origin}/mcp/${profile}\nAuthorization: ${authHeader(token)}`,
    prompt: connectPrompt,
  },
];

export function guidedClients(): GuidedClient[] {
  return CLIENTS.filter((c): c is GuidedClient => c.kind === "guided");
}
