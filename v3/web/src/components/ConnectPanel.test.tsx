/**
 * Issue 270: the per-vault read/save picker in `ConnectPanel`'s "Issue
 * token" step. Three cases mirror the issue's own "Suggested acceptance":
 * the picker shows the target profile's vaults all checked by default,
 * unchecking a box narrows what gets sent, and a caller who never touches
 * the picker gets the exact one-click flow that existed before it.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GatewayProfile } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { GuidedClient } from "../lib/clients";
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
  command: (origin, profile) => `connect ${origin}/mcp/${profile}`,
  prompt: (origin, profile) => `Please connect to ${origin}/mcp/${profile}`,
};

const DEFAULT_PROFILE: GatewayProfile = {
  path: "default",
  label: null,
  vaults: ["work", "personal"],
  stash: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: false,
};

function mount() {
  return render(
    <ToastProvider>
      <ConnectPanel client={CLIENT} />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ConnectPanel's read/save picker (issue #270)", () => {
  it("shows every vault the target profile mounts, read and save both checked by default", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);

    mount();

    expect(await screen.findByText("work")).toBeInTheDocument();
    expect(screen.getByText("personal")).toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(checkboxes).toHaveLength(4); // read + save, for each of two vaults
    for (const checkbox of checkboxes) {
      expect(checkbox.checked).toBe(true);
    }
  });

  it("sends the narrower explicit list once a box is unchecked, instead of an empty one", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    const createSpy = vi.spyOn(api, "createToken").mockResolvedValue({
      info: {
        id: "tok_1",
        name: "Test Client",
        profile: "default",
        scopes: [],
        created_at: "2026-01-01T00:00:00Z",
        revoked_at: null,
        last_used_at: null,
      },
      token: "plt_secret",
    });

    mount();

    await screen.findByText("work");
    const rows = screen.getAllByRole("checkbox");
    // Row order: work-read, work-save, personal-read, personal-save.
    fireEvent.click(rows[1]!); // uncheck "work"'s Save box

    fireEvent.click(screen.getByRole("button", { name: /issue token/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy).toHaveBeenCalledWith({
      name: "Test Client",
      profile: "default",
      scopes: ["vault:work:read", "vault:personal:read", "vault:personal:write"],
    });
  });

  it("leaves the one-click flow unaffected when nobody touches the picker", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    const createSpy = vi.spyOn(api, "createToken").mockResolvedValue({
      info: {
        id: "tok_1",
        name: "Test Client",
        profile: "default",
        scopes: [],
        created_at: "2026-01-01T00:00:00Z",
        revoked_at: null,
        last_used_at: null,
      },
      token: "plt_secret",
    });

    mount();

    await screen.findByText("work");
    fireEvent.click(screen.getByRole("button", { name: /issue token/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    // No `scopes` field at all — byte-for-byte what this call sent before
    // the picker existed, so the server's own default keeps deciding.
    expect(createSpy).toHaveBeenCalledWith({ name: "Test Client", profile: "default" });
  });

  it("degrades to no picker, and the one-click flow still works, when no gateway is attached", async () => {
    vi.spyOn(api, "listTokens").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(new Error("no gateway attached"));
    const createSpy = vi.spyOn(api, "createToken").mockResolvedValue({
      info: {
        id: "tok_1",
        name: "Test Client",
        profile: "default",
        scopes: [],
        created_at: "2026-01-01T00:00:00Z",
        revoked_at: null,
        last_used_at: null,
      },
      token: "plt_secret",
    });

    mount();

    await screen.findByRole("button", { name: /issue token/i });
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: /issue token/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy).toHaveBeenCalledWith({ name: "Test Client", profile: "default" });
  });
});
