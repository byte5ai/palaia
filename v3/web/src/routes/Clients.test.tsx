import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import axe from "axe-core";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { GatewayProfile, ModeStatus, TokenInfo } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { CLIENTS } from "../lib/clients";
import { Clients } from "./Clients";

const DEFAULT_PROFILE: GatewayProfile = {
  path: "default",
  label: null,
  vaults: ["work"],
  stash: false,
  telegram: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: false,
};

const CODEX_ONLY_PROFILE: GatewayProfile = { ...DEFAULT_PROFILE, path: "codex-only", tool_count: 4 };

function key(name: string, overrides: Partial<TokenInfo> = {}): TokenInfo {
  return {
    id: `t-${name}`,
    name,
    profile: "default",
    scopes: [],
    created_at: "2026-10-01T00:00:00Z",
    revoked_at: null,
    last_used_at: null,
    ...overrides,
  };
}

function stub({
  mode = "locked",
  issuer = null,
  tokens = [],
  profiles = [DEFAULT_PROFILE],
}: {
  mode?: "locked" | "cloud" | "open";
  issuer?: string | null;
  tokens?: TokenInfo[] | Error;
  profiles?: GatewayProfile[];
} = {}) {
  vi.spyOn(api, "mode").mockResolvedValue({
    active_mode: mode,
    configured_mode: mode,
    restart_required: false,
    oauth_enabled: issuer !== null,
    oauth_issuer: issuer,
  } as unknown as ModeStatus);
  if (tokens instanceof Error) vi.spyOn(api, "listTokens").mockRejectedValue(tokens);
  else vi.spyOn(api, "listTokens").mockResolvedValue(tokens);
  vi.spyOn(api, "listGatewayProfiles").mockResolvedValue(profiles);
  vi.spyOn(api, "tokenUsage").mockRejectedValue(new ApiError("/api/auth/tokens/usage", 404, {}));
}

function mount() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Clients />
      </ToastProvider>
    </MemoryRouter>,
  );
}

function row(name: RegExp): HTMLElement {
  return screen.getByRole("button", { name });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AI apps › Apps (report §3.5)", () => {
  it("lists every supported app with its status and says how many are connected", async () => {
    stub({
      tokens: [
        key("Claude Code CLI", { last_used_at: new Date(Date.now() - 120_000).toISOString() }),
        key("Codex"),
      ],
    });
    mount();

    expect(await screen.findByText(`1 of ${CLIENTS.length} connected`)).toBeInTheDocument();
    for (const client of CLIENTS) {
      expect(screen.getByText(client.name, { selector: ".listrow__title" })).toBeInTheDocument();
    }
    expect(row(/^claude code cli/i)).toHaveTextContent("Connected");
    expect(row(/^claude code cli/i)).toHaveTextContent("Last request 2 min ago");
    expect(row(/^codex/i)).toHaveTextContent("Waiting for first use");
    expect(row(/^lm studio/i)).toHaveTextContent("Ready to connect");
  });

  it("says a cloud app needs Cloud mode in Private mode, with the way to set it up", async () => {
    stub({ mode: "locked" });
    mount();

    fireEvent.click(await screen.findByRole("button", { name: /^chatgpt/i }));

    expect(row(/^chatgpt/i)).toHaveTextContent("Needs Cloud mode");
    expect(screen.getByText("ChatGPT needs Cloud mode")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up Cloud mode" })).toHaveAttribute("href", "/settings/access");
    // The plan limit from the catalog is still said.
    expect(screen.getByText(/write access needs a business/i)).toBeInTheDocument();
  });

  it("gives a cloud app its address once Cloud mode has sign-in for AI apps", async () => {
    stub({ mode: "cloud", issuer: "https://palaia.example.com" });
    mount();

    // The Claude app and claude.ai share one cloud entry ("Claude", issue 565).
    const claude = (await screen.findByText("Claude", { selector: ".listrow__title" })).closest("button")!;
    fireEvent.click(claude);

    expect(claude).toHaveTextContent("Ready to connect");
    expect(screen.getByText("https://palaia.example.com/mcp/default")).toBeInTheDocument();
  });

  it("starts the default app at Create access key", async () => {
    stub();
    mount();

    expect(await screen.findByRole("button", { name: /create access key/i })).toBeInTheDocument();
  });

  it("an error loading the apps is an error, never an empty list", async () => {
    stub({ tokens: new ApiError("/api/auth/tokens", 500, { detail: "database is locked" }) });
    mount();

    expect(await screen.findByText("Couldn't load your AI apps")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText(/connected$/)).not.toBeInTheDocument();
  });

  it("updates an app's row when its access key is revoked", async () => {
    stub({ tokens: [key("Claude Code CLI", { last_used_at: new Date().toISOString() })] });
    vi.spyOn(api, "revokeToken").mockResolvedValue(undefined);
    mount();

    await waitFor(() => expect(row(/^claude code cli/i)).toHaveTextContent("Connected"));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke access" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke access" }));

    await waitFor(() => expect(row(/^claude code cli/i)).toHaveTextContent("Ready to connect"));
  });
});

describe("Claude Desktop — the one-click extension (SPEC-306)", () => {
  it("downloads a real extension on click, for the tool set picked under Advanced", async () => {
    stub({ profiles: [DEFAULT_PROFILE, CODEX_ONLY_PROFILE] });
    const download = vi
      .spyOn(api, "downloadFile")
      .mockResolvedValue({ blob: new Blob(["fake mcpb bytes"]), filename: "palaia.mcpb" });
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:test", revokeObjectURL: () => {} }),
    );
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /^claude desktop/i }));
    fireEvent.change(await screen.findByLabelText("Tool set"), { target: { value: "codex-only" } });
    fireEvent.click(screen.getByRole("button", { name: /download extension/i }));

    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(String(download.mock.calls[0]![0])).toContain("/api/connect/mcpb?profile=codex-only");
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  });

  it("shows palaia's own reason when it cannot build one", async () => {
    stub();
    vi.spyOn(api, "downloadFile").mockRejectedValue(
      new ApiError("/api/connect/mcpb", 501, { detail: "no client-authentication method is configured" }),
    );

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /^claude desktop/i }));
    fireEvent.click(await screen.findByRole("button", { name: /download extension/i }));

    expect(await screen.findByText(/no client-authentication method is configured/i)).toBeInTheDocument();
  });
});

/** principles.md §0.1: no protocol word in a label, heading, button, pill or option. */
describe("AI apps copy — no jargon in the surface", () => {
  const BANNED = [/\bmcp\b/i, /\boauth\b/i, /\btoken\b/i, /\bprofile\b/i, /\bendpoint\b/i, /\bvault\b/i, /\bbearer\b/i];

  it("no heading, button, pill or field label uses an implementation word", async () => {
    stub({ profiles: [DEFAULT_PROFILE, CODEX_ONLY_PROFILE] });
    mount();
    await screen.findByRole("button", { name: /create access key/i });

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("tab"),
      ...Array.from(document.querySelectorAll(".pill, .badge, .card__title, .field__label, summary, option")),
    ];
    expect(controls.length).toBeGreaterThan(10);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) expect(text, text).not.toMatch(pattern);
    }
  });
});

describe("AI apps accessibility", () => {
  it("the list and the connect flow have no serious axe-core violations", async () => {
    stub({
      tokens: [key("Codex")],
      profiles: [DEFAULT_PROFILE, CODEX_ONLY_PROFILE],
    });
    mount();
    await screen.findByRole("button", { name: /create access key/i });
    fireEvent.click(row(/^codex/i));
    await screen.findByRole("tablist");

    const results = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`)).toEqual([]);
  });
});
