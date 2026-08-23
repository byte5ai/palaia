/**
 * The client integration catalog (SPEC-110), read straight off
 * MASTERPLAN.md §6's client integration matrix — every entry there gets a
 * row here, so "every §6-matrix client has a connect flow" (this SPEC's
 * acceptance criterion) is checkable by diffing this array against that
 * table, not by memory.
 *
 * Two kinds of entry:
 * - `guided`: the client connects to *this device* (a local process, or a
 *   custom MCP config it owns) — always reachable, in every operating
 *   mode, because nothing outside the operator's own network is involved.
 *   These get the real, working flow: `ConnectPanel` issues a token
 *   through the already-built `/api/auth/tokens` (SPEC-108) and shows the
 *   copy-command / paste-prompt pair.
 * - `notYet`: the client connects *from the vendor's cloud* (claude.ai,
 *   ChatGPT, Grok) or needs a delivery mechanism this phase does not build
 *   yet (Claude Desktop's MCPB bundle, Phase 3). `notYetReason(mode)`
 *   returns the truthful, mode-aware explanation this SPEC's acceptance
 *   criterion asks for — never a dead end, always why and what changes it.
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

export interface GuidedClient {
  kind: "guided";
  id: string;
  name: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  estimate: string;
  /** The one-liner for the "copy the command" tab. */
  command: (origin: string, profile: string) => string;
  /** The self-configuring prompt for the "paste a prompt" tab. */
  prompt: (origin: string, profile: string) => string;
}

export interface NotYetClient {
  kind: "notYet";
  id: string;
  name: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  subtitle: string;
  /** Truthful, mode-aware explanation — never just "not available". */
  reason: (mode: HubMode) => string;
}

export type ClientEntry = GuidedClient | NotYetClient;

const CLOUD_CONNECTOR_REASON = (name: string, planNote: string) => (mode: HubMode): string =>
  mode === "locked"
    ? `${name} connects from its own cloud, not from this device — Locked mode only answers ` +
      `inside your network, so it would time out whatever you paste into it. Switch to Cloud or ` +
      `Open mode to expose an endpoint it can reach.`
    : `${name}'s connector needs sign-in (OAuth) to reach a hub that is not on Anthropic's or ` +
      `OpenAI's own infrastructure — that sign-in flow is Phase 2 work and is not built yet. ` +
      `${planNote}`;

export const CLIENTS: ClientEntry[] = [
  {
    kind: "guided",
    id: "claude-code-cli",
    name: "Claude Code CLI",
    icon: SparkleIcon,
    estimate: "one command · 1 min",
    command: (origin, profile) => `claude mcp add --transport http palaia ${origin}/mcp/${profile}`,
    prompt: (origin, profile) =>
      `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
      `Then run a test recall and tell me what you found.`,
  },
  {
    kind: "guided",
    id: "codex",
    name: "Codex",
    icon: ToolsIcon,
    estimate: "one command · 1 min",
    command: (origin, profile) => `codex mcp add palaia --transport http ${origin}/mcp/${profile}`,
    prompt: (origin, profile) =>
      `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
      `Then run a test recall and tell me what you found.`,
  },
  {
    kind: "notYet",
    id: "claude-desktop",
    name: "Claude Code (Desktop app)",
    icon: ExplorerIcon,
    subtitle: "One-click MCPB bundle — signed, local-only by spec",
    reason: () =>
      "Claude Code (Desktop app) connects through a signed MCPB bundle (a thin stdio→hub proxy, " +
      "since MCPB is local-only by spec) — palaia does not build and sign that bundle yet. " +
      "Planned for Phase 3; use Claude Code CLI in the meantime, on the same machine.",
  },
  {
    kind: "notYet",
    id: "claude-ai",
    name: "claude.ai",
    icon: LinkIcon,
    subtitle: "Web, desktop, mobile and Cowork — custom connector on every plan",
    reason: CLOUD_CONNECTOR_REASON(
      "claude.ai",
      "Once it ships, every plan (including Free) can add palaia as a custom connector.",
    ),
  },
  {
    kind: "notYet",
    id: "chatgpt",
    name: "ChatGPT",
    icon: LinkIcon,
    subtitle: "Developer mode / custom connectors",
    reason: CLOUD_CONNECTOR_REASON(
      "ChatGPT",
      "Once it ships: write access needs a Business, Enterprise or Edu workspace — Plus/Pro will " +
        "get a read-only profile so recall still works.",
    ),
  },
  {
    kind: "guided",
    id: "gemini-cli",
    name: "Antigravity / Gemini CLI",
    icon: ClientsIcon,
    estimate: "one command · 1 min",
    command: (origin, profile) =>
      `# add to ~/.gemini/settings.json under "mcpServers"\n` +
      `{"palaia": {"httpUrl": "${origin}/mcp/${profile}"}}`,
    prompt: (origin, profile) =>
      `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
      `Then run a test recall and tell me what you found.`,
  },
  {
    kind: "notYet",
    id: "grok",
    name: "Grok",
    icon: ClientsIcon,
    subtitle: "Custom (bring-your-own) MCP connectors — web/iOS/Android",
    reason: CLOUD_CONNECTOR_REASON("Grok", "Once it ships, connect from web, iOS or Android."),
  },
  {
    kind: "guided",
    id: "lm-studio",
    name: "LM Studio",
    icon: ToolsIcon,
    estimate: "one command · 1 min",
    command: (origin, profile) => `# LM Studio → Program → mcp.json\n{"palaia": {"url": "${origin}/mcp/${profile}"}}`,
    prompt: (origin, profile) =>
      `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
      `Then run a test recall and tell me what you found.`,
  },
  {
    kind: "guided",
    id: "generic",
    name: "Any other AI tool",
    icon: ExplorerIcon,
    estimate: "endpoint and token",
    command: (origin, profile) => `${origin}/mcp/${profile}`,
    prompt: (origin, profile) =>
      `Please connect yourself to my palaia hub as an MCP server:\n${origin}/mcp/${profile}\n` +
      `Then run a test recall and tell me what you found.`,
  },
];

export function guidedClients(): GuidedClient[] {
  return CLIENTS.filter((c): c is GuidedClient => c.kind === "guided");
}
