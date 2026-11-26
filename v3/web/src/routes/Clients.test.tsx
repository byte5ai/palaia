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

function mount(at = "/apps") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <ToastProvider>
        <Clients />
      </ToastProvider>
    </MemoryRouter>,
  );
}

/** The table row of one app. */
function row(name: string): HTMLElement {
  return screen.getByRole("rowheader", { name }).closest("tr")!;
}

/** Opens an app's side panel through its row's button. */
async function openApp(name: string): Promise<HTMLElement> {
  await screen.findByRole("rowheader", { name });
  fireEvent.click(within(row(name)).getByRole("button"));
  return screen.findByRole("dialog", { name });
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
      expect(screen.getByRole("rowheader", { name: client.name })).toBeInTheDocument();
    }
    expect(row("Claude Code CLI")).toHaveTextContent("Connected");
    expect(row("Claude Code CLI")).toHaveTextContent("2 min ago");
    expect(row("Codex")).toHaveTextContent("Waiting for first use");
    // An app nobody touched says so in plain text: no pill repeated per row.
    expect(row("LM Studio")).toHaveTextContent("Not connected");
    expect(row("LM Studio").querySelector(".pill")).toBeNull();
  });

  it("lists the apps in use first, and each row's button says what it opens", async () => {
    stub({ tokens: [key("Codex")] });
    mount();

    await screen.findByRole("rowheader", { name: "Codex" });
    const headers = screen.getAllByRole("rowheader");
    expect(headers[0]).toHaveTextContent("In use · 1");
    expect(headers[1]).toHaveAccessibleName("Codex");
    expect(headers[2]).toHaveTextContent(`Available · ${CLIENTS.length - 1}`);
    expect(within(row("Codex")).getByRole("button", { name: "Manage: Codex" })).toBeInTheDocument();
    expect(within(row("LM Studio")).getByRole("button", { name: "Connect: LM Studio" })).toBeInTheDocument();
    expect(within(row("ChatGPT")).getByRole("button", { name: "How to connect: ChatGPT" })).toBeInTheDocument();
    // Nothing is open until a row is chosen.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("says a cloud app needs Cloud mode in Private mode, with the way to set it up", async () => {
    stub({ mode: "locked" });
    mount();

    await openApp("ChatGPT");

    expect(row("ChatGPT")).toHaveTextContent("Needs Cloud mode");
    expect(screen.getByText("ChatGPT needs Cloud mode")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up Cloud mode" })).toHaveAttribute("href", "/settings/access");
    // The plan limit from the catalog is still said.
    expect(screen.getByText(/write access needs a business/i)).toBeInTheDocument();
  });

  it("gives a cloud app its address once Cloud mode has sign-in for AI apps", async () => {
    stub({ mode: "cloud", issuer: "https://palaia.example.com" });
    mount();

    // The Claude app and claude.ai share one cloud entry ("Claude", issue 565).
    await openApp("Claude");

    expect(row("Claude")).toHaveTextContent("Signs in with your palaia account");
    expect(screen.getByText("https://palaia.example.com/mcp/default")).toBeInTheDocument();
  });

  it("offers an Add to Claude link with only the public address, next to the copyable address", async () => {
    stub({ mode: "cloud", issuer: "https://palaia.example.com" });
    mount();

    const panel = await openApp("Claude");

    const button = within(panel).getByRole("link", { name: "Add to Claude" });
    expect(button).toHaveAttribute(
      "href",
      "https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=palaia" +
        "&connectorUrl=https%3A%2F%2Fpalaia.example.com%2Fmcp%2Fdefault",
    );
    expect(button).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
    expect(decodeURIComponent(button.getAttribute("href")!)).not.toContain(window.location.origin);
    // The copy-the-address way stays.
    expect(within(panel).getByText("https://palaia.example.com/mcp/default")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });

  it("has no Add to Claude link without cloud access, and none for ChatGPT", async () => {
    stub({ mode: "locked" });
    mount();
    const panel = await openApp("Claude");
    expect(within(panel).getByText("Claude needs Cloud mode")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add to Claude" })).not.toBeInTheDocument();

    vi.restoreAllMocks();
    stub({ mode: "cloud", issuer: "https://palaia.example.com" });
    mount("/apps?app=chatgpt");
    expect(await screen.findByRole("dialog", { name: "ChatGPT" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add to Claude" })).not.toBeInTheDocument();
  });

  it("an app's panel has its own address and starts at Create access key", async () => {
    stub();
    mount("/apps?app=claude-code-cli");

    const panel = await screen.findByRole("dialog", { name: "Claude Code CLI" });
    expect(within(panel).getByRole("button", { name: /create access key/i })).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
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

    await waitFor(() => expect(row("Claude Code CLI")).toHaveTextContent("Connected"));
    await openApp("Claude Code CLI");
    fireEvent.click(await screen.findByRole("button", { name: "Revoke access" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: /revoke access/i })).getByRole("button", { name: "Revoke access" }),
    );

    await waitFor(() => expect(row("Claude Code CLI")).toHaveTextContent("Not connected"));
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
    await openApp("Claude Desktop");
    fireEvent.change(await screen.findByLabelText("Tool set"), { target: { value: "codex-only" } });
    fireEvent.click(screen.getByRole("button", { name: /download extension/i }));

    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(String(download.mock.calls[0]![0])).toContain("/api/connect/mcpb?profile=codex-only");
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  });

  /** A hub that makes a new access key for every extension download (no
   * sign-in server: `mcpb/routes.py`), and revokes what it is told to. */
  function desktopHub(initial: TokenInfo[]) {
    const keys = initial.map((k) => ({ ...k }));
    stub();
    vi.spyOn(api, "listTokens").mockImplementation(async () => keys.map((k) => ({ ...k })));
    vi.spyOn(api, "downloadFile").mockImplementation(async () => {
      keys.push(key("Claude Desktop", { id: `t-download-${keys.length}` }));
      return { blob: new Blob(["fake mcpb bytes"]), filename: "palaia.mcpb" };
    });
    const revoke = vi.spyOn(api, "revokeToken").mockImplementation(async (id: string) => {
      const found = keys.find((k) => k.id === id);
      if (found) found.revoked_at = new Date().toISOString();
    });
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:test", revokeObjectURL: () => {} }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    return { keys, revoke };
  }

  it("revoking stops every extension, also one downloaded after the page loaded", async () => {
    const hub = desktopHub([key("Claude Desktop", { id: "t-old" })]);

    mount();
    await openApp("Claude Desktop");
    fireEvent.click(await screen.findByRole("button", { name: /download extension/i }));
    await waitFor(() => expect(hub.keys).toHaveLength(2));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke access" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: /revoke access/i })).getByRole("button", { name: "Revoke access" }),
    );

    await waitFor(() => expect(hub.keys.every((k) => k.revoked_at !== null)).toBe(true));
    expect(hub.revoke).toHaveBeenCalledWith("t-download-1");
  });

  it("offers Revoke access right after the first download", async () => {
    desktopHub([]);

    mount();
    await openApp("Claude Desktop");
    expect(screen.queryByRole("button", { name: "Revoke access" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /download extension/i }));

    expect(await screen.findByRole("button", { name: "Revoke access" })).toBeInTheDocument();
  });

  it("shows palaia's own reason when it cannot build one", async () => {
    stub();
    vi.spyOn(api, "downloadFile").mockRejectedValue(
      new ApiError("/api/connect/mcpb", 501, { detail: "no client-authentication method is configured" }),
    );

    mount();
    await openApp("Claude Desktop");
    fireEvent.click(await screen.findByRole("button", { name: /download extension/i }));

    expect(await screen.findByText(/no client-authentication method is configured/i)).toBeInTheDocument();
  });
});

/** principles.md §0.1: no protocol word in a label, heading, button, pill or option. */
describe("AI apps copy — no jargon in the surface", () => {
  const BANNED = [/\bmcp\b/i, /\boauth\b/i, /\btoken\b/i, /\bprofile\b/i, /\bendpoint\b/i, /\bvault\b/i, /\bbearer\b/i];

  it("no heading, button, pill or field label uses an implementation word", async () => {
    stub({ profiles: [DEFAULT_PROFILE, CODEX_ONLY_PROFILE] });
    mount("/apps?app=claude-code-cli");
    await screen.findByRole("button", { name: /create access key/i });

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("tab"),
      ...screen.queryAllByRole("columnheader"),
      ...Array.from(document.querySelectorAll(".pill, .badge, .card__title, .field__label, summary, option, caption")),
    ];
    expect(controls.length).toBeGreaterThan(10);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) expect(text, text).not.toMatch(pattern);
    }
  });
});

describe("AI apps accessibility", () => {
  it("the table and the connect panel have no serious axe-core violations", async () => {
    stub({
      tokens: [key("Codex")],
      profiles: [DEFAULT_PROFILE, CODEX_ONLY_PROFILE],
    });
    mount();
    await openApp("Codex");
    await screen.findByRole("tablist");

    const results = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`)).toEqual([]);
  });
});
