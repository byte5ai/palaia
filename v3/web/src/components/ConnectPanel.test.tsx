/**
 * ConnectPanel — connecting one AI app.
 *
 * Issue 270: per-memory Read/Save, all checked; untouched sends no `scopes`
 * (the server default), unchecking sends a narrower list, unchecking all is
 * blocked. Issue 318: the snippets carry the freshly created access key; a
 * panel that only found an existing key says how to get a new one. Report
 * §3.4/§5.5: only existing tool sets can be chosen (under Advanced), and
 * access can be revoked or the key replaced.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GatewayProfile, TokenInfo } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { GuidedClient } from "../lib/clients";
import { TOKEN_PLACEHOLDER } from "../lib/clients";
import { ConnectPanel } from "./ConnectPanel";
import { ToastProvider } from "./Toast";

function DummyIcon() {
  return null;
}

const CLIENT: GuidedClient = {
  kind: "guided",
  id: "test-client",
  name: "Test Client",
  icon: DummyIcon,
  estimate: "one command · 1 min",
  command: (origin, profile, token) =>
    `connect ${origin}/mcp/${profile} --token ${token ?? TOKEN_PLACEHOLDER}`,
  prompt: (origin, profile, token) =>
    `Please connect to ${origin}/mcp/${profile} with ${token ?? TOKEN_PLACEHOLDER}`,
  configFile: (origin, profile, token) => ({
    filename: "test.json",
    mimeType: "application/json",
    content: `{"url": "${origin}/mcp/${profile}", "token": "${token ?? TOKEN_PLACEHOLDER}"}`,
  }),
};

const KEY: TokenInfo = {
  id: "tok_1",
  name: "Test Client",
  profile: "default",
  scopes: ["vault:work:read", "vault:work:write"],
  created_at: "2026-01-01T00:00:00Z",
  revoked_at: null,
  last_used_at: null,
};

const ISSUED = { info: KEY, token: "plt_secret" };

const DEFAULT_PROFILE: GatewayProfile = {
  path: "default",
  label: null,
  vaults: ["work", "personal"],
  stash: false,
  telegram: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: false,
};

const CODEX_ONLY: GatewayProfile = { ...DEFAULT_PROFILE, path: "codex-only", vaults: ["work"], tool_count: 4 };

function mount(props: Partial<Parameters<typeof ConnectPanel>[0]> = {}) {
  return render(
    <ToastProvider>
      <ConnectPanel client={CLIENT} {...props} />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("choosing what the app can use (issue 270)", () => {
  it("lists every memory of the tool set, Read and Save both checked", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);

    mount();

    expect(await screen.findByText("Choose what Test Client can use")).toBeInTheDocument();
    expect(await screen.findByText("work")).toBeInTheDocument();
    expect(screen.getByText("personal")).toBeInTheDocument();
    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes).toHaveLength(4);
    expect(boxes.every((box) => box.checked)).toBe(true);
    expect(screen.getByLabelText("Save to work")).toBeChecked();
  });

  it("sends the narrower list once a box is unchecked", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    const create = vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);

    mount();
    fireEvent.click(await screen.findByLabelText("Save to work"));
    fireEvent.click(screen.getByRole("button", { name: /create access key/i }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({
      name: "Test Client",
      profile: "default",
      scopes: ["vault:work:read", "vault:personal:read", "vault:personal:write"],
    });
  });

  it("sends no scopes at all when nobody touches the boxes", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    const create = vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);

    mount();
    await screen.findByText("work");
    fireEvent.click(screen.getByRole("button", { name: /create access key/i }));

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({ name: "Test Client", profile: "default" });
  });

  it("blocks creating a key that would grant nothing", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([{ ...DEFAULT_PROFILE, vaults: ["work"] }]);

    mount();
    fireEvent.click(await screen.findByLabelText("Read work"));
    fireEvent.click(screen.getByLabelText("Save to work"));

    expect(screen.getByRole("alert")).toHaveTextContent("Select at least one memory.");
    expect(screen.getByRole("button", { name: /create access key/i })).toBeDisabled();
  });

  it("still creates a key, without a picker, when no tool sets are known", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));
    const create = vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /create access key/i }));

    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "Test Client", profile: "default" }));
  });
});

describe("the tool set (report §3.4)", () => {
  it("offers only existing tool sets, under Advanced, and creates the key for the one picked", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE, CODEX_ONLY]);
    const create = vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);

    mount();
    await screen.findByText("personal");
    // No free-text name anywhere.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    const select = screen.getByLabelText("Tool set") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["default", "codex-only"]);
    fireEvent.change(select, { target: { value: "codex-only" } });
    expect(screen.queryByText("personal")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /create access key/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({ name: "Test Client", profile: "codex-only" }),
    );
  });

  it("never suggests a tool set that does not exist", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([CODEX_ONLY]);
    const create = vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);

    mount({ defaultProfile: "default" });
    await screen.findByText("work");
    fireEvent.click(screen.getByRole("button", { name: /create access key/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({ name: "Test Client", profile: "codex-only" }),
    );
  });
});

describe("the access key in the snippets (issue 318)", () => {
  it("fills the new key into the command, prompt and config file, and shows it once", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));
    vi.spyOn(api, "createToken").mockResolvedValue(ISSUED);
    vi.stubGlobal(
      "URL",
      Object.assign(URL, { createObjectURL: () => "blob:test", revokeObjectURL: () => {} }),
    );

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /create access key/i }));

    const command = await screen.findByText(/^connect .*\/mcp\/default --token plt_secret$/);
    expect(command.textContent).not.toContain(TOKEN_PLACEHOLDER);
    expect(screen.getByText("Access key (shown once)")).toBeInTheDocument();
    expect(screen.getByText(/palaia can.t show it again/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Prompt" }));
    expect(screen.getByText(/with plt_secret$/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Config file" }));
    expect(screen.getByText(/"token": "plt_secret"/)).toBeInTheDocument();
  });

  it("an existing key's command shows the placeholder and says how to get a new key", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([KEY]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));

    mount();

    const command = await screen.findByText(/^connect .*\/mcp\/default --token /);
    expect(command.textContent).toContain(TOKEN_PLACEHOLDER);
    expect(screen.getByText(/lost it\? replace the access key/i)).toBeInTheDocument();
    expect(screen.queryByText("plt_secret")).not.toBeInTheDocument();
    expect(screen.getByText("Waiting for first use")).toBeInTheDocument();
  });

  it("says when the app is connected", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([
      { ...KEY, last_used_at: new Date(Date.now() - 120_000).toISOString() },
    ]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));

    mount();

    expect(await screen.findAllByText(/connected — last request 2 min ago/i)).not.toHaveLength(0);
    expect(screen.getByText("Connected", { selector: ".pill" })).toBeInTheDocument();
  });
});

describe("revoking and replacing (report §5.5)", () => {
  it("revokes every live key of the app after a confirmation, and starts over", async () => {
    const other = { ...KEY, id: "tok_2" };
    vi.spyOn(api, "listTokens").mockResolvedValue([KEY, other, { ...KEY, id: "x", name: "Another app" }]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));
    const revoke = vi.spyOn(api, "revokeToken").mockResolvedValue(undefined);
    const onTokenRevoked = vi.fn();

    mount({ onTokenRevoked });
    fireEvent.click(await screen.findByRole("button", { name: "Revoke access" }));
    const dialog = screen.getByRole("dialog", { name: "Revoke access for Test Client?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Revoke access" }));

    await waitFor(() => expect(onTokenRevoked).toHaveBeenCalled());
    expect(revoke.mock.calls.map((call) => call[0]).sort()).toEqual(["tok_1", "tok_2"]);
    expect(await screen.findByRole("button", { name: /create access key/i })).toBeInTheDocument();
  });

  it("replaces the key: a new one with the same permissions, then the old one revoked", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([KEY]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway"));
    const create = vi
      .spyOn(api, "createToken")
      .mockResolvedValue({ info: { ...KEY, id: "tok_new" }, token: "plt_new" });
    const revoke = vi.spyOn(api, "revokeToken").mockResolvedValue(undefined);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Replace access key" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Replace access key" }));

    await waitFor(() => expect(revoke).toHaveBeenCalledWith("tok_1"));
    expect(create).toHaveBeenCalledWith({
      name: "Test Client",
      profile: "default",
      scopes: ["vault:work:read", "vault:work:write"],
    });
    expect(revoke).not.toHaveBeenCalledWith("tok_new");
    expect(await screen.findByText(/--token plt_new$/)).toBeInTheDocument();
  });
});
