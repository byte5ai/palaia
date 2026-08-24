import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type {
  GatewayProfile,
  GatewayTool,
  GatewayUpstream,
  GatewayVaultIdentity,
  VaultSummary,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { ToolProfiles } from "./ToolProfiles";

const NOT_MOUNTED = new ApiError("/api/gateway/profiles", 404, undefined);

const WORK_VAULT: VaultSummary = {
  key: "work",
  purpose: "Work knowledge.",
  path: "/vaults/work",
  writable: true,
  note_count: 3,
};

const DEFAULT_PROFILE: GatewayProfile = {
  path: "default",
  label: null,
  vaults: ["work"],
  stash: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: false,
};

const CURATOR_PROFILE: GatewayProfile = {
  path: "curator",
  label: null,
  vaults: ["work"],
  stash: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: true,
};

const FETCH_UPSTREAM: GatewayUpstream = {
  key: "fetch",
  kind: "stdio",
  display_name: "Fetch",
  namespace: "fetch",
  enabled: true,
  target: "docker run --rm -i ghcr.io/palaia/addon-fetch:1.0.0",
  profiles: [],
  up: true,
  status: "Connected — 1 tool.",
  checked_at: 1_700_000_000,
  tools: ["fetch"],
  secret_names: [],
  tool_renames: {},
};

const WORK_TOOLS: GatewayTool[] = [
  { name: "work_memory_search", description: "Search the work vault.", hidden: false },
  { name: "work_memory_delete", description: "Delete a note.", hidden: false },
];

const WORK_VAULT_IDENTITY: GatewayVaultIdentity = {
  key: "work",
  name: "work",
  purpose: "Work knowledge.",
  tool_renames: {},
  namespace: "work_memory",
  sanitized: [],
};

function mount() {
  return render(
    <ToastProvider>
      <ToolProfiles />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ToolProfiles screen (SPEC-305)", () => {
  it("degrades gracefully when no gateway is attached", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockRejectedValue(NOT_MOUNTED);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([]);
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);

    mount();

    expect(
      await screen.findByText(/no gateway attached/i),
    ).toBeInTheDocument();
  });

  it("lists the live tool count for each profile", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);

    mount();

    expect(await screen.findByText("default")).toBeInTheDocument();
    expect(screen.getByText("15 tools")).toBeInTheDocument();
  });

  it("shows the curator profile as managed, with no edit/delete controls", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([CURATOR_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);

    mount();

    expect(await screen.findByText(/managed elsewhere/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
  });

  it("creates a profile through the form", async () => {
    const listSpy = vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);
    const createSpy = vi.spyOn(api, "createGatewayProfile").mockResolvedValue({
      ...DEFAULT_PROFILE,
      path: "codex",
      tool_count: 15,
    });

    mount();
    await screen.findByText(/no tool profiles yet/i);

    fireEvent.click(screen.getByRole("button", { name: /new tool profile/i }));
    fireEvent.change(screen.getByLabelText(/address segment/i), {
      target: { value: "Codex!" },
    });
    fireEvent.click(screen.getByLabelText("work"));
    listSpy.mockResolvedValue([{ ...DEFAULT_PROFILE, path: "codex" }]);
    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({ path: "codex", vaults: ["work"], upstreams: [] }),
      ),
    );
  });

  it("assigns a connected tool to a new profile through its checkbox", async () => {
    const listSpy = vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([FETCH_UPSTREAM]);
    const createSpy = vi.spyOn(api, "createGatewayProfile").mockResolvedValue({
      ...DEFAULT_PROFILE,
      path: "codex",
      upstreams: ["fetch"],
    });

    mount();
    await screen.findByText(/no tool profiles yet/i);

    fireEvent.click(screen.getByRole("button", { name: /new tool profile/i }));
    fireEvent.change(screen.getByLabelText(/address segment/i), {
      target: { value: "codex" },
    });
    fireEvent.click(await screen.findByLabelText(/^fetch/i));
    listSpy.mockResolvedValue([{ ...DEFAULT_PROFILE, path: "codex", upstreams: ["fetch"] }]);
    fireEvent.click(screen.getByRole("button", { name: /^create$/i }));

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith(expect.objectContaining({ upstreams: ["fetch"] })),
    );
  });

  it("edits a profile's hidden tools and saves them", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([FETCH_UPSTREAM]);
    vi.spyOn(api, "listGatewayProfileTools").mockResolvedValue(WORK_TOOLS);
    const updateSpy = vi.spyOn(api, "updateGatewayProfile").mockResolvedValue({
      ...DEFAULT_PROFILE,
      hidden_tools: ["work_memory_delete"],
    });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /^edit$/i }));

    const deleteCheckbox = await screen.findByText("work_memory_delete");
    fireEvent.click(deleteCheckbox.closest("label")!.querySelector("input")!);
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith(
        "default",
        expect.objectContaining({ hidden_tools: ["work_memory_delete"] }),
      ),
    );
  });

  it("assigns an already-connected tool to an existing profile through its checkbox", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([FETCH_UPSTREAM]);
    vi.spyOn(api, "listGatewayProfileTools").mockResolvedValue(WORK_TOOLS);
    const updateSpy = vi.spyOn(api, "updateGatewayProfile").mockResolvedValue({
      ...DEFAULT_PROFILE,
      upstreams: ["fetch"],
    });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /^edit$/i }));
    fireEvent.click(await screen.findByLabelText(/^fetch/i));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith(
        "default",
        expect.objectContaining({ upstreams: ["fetch"] }),
      ),
    );
  });

  it("cannot delete the default profile", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);

    mount();

    expect(await screen.findByText(/cannot delete the default profile/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it("renames a vault's tool and reports a sanitized value", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([]);
    const listVaultsSpy = vi
      .spyOn(api, "listGatewayVaults")
      .mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "updateGatewayVault").mockResolvedValue({
      ...WORK_VAULT_IDENTITY,
      tool_renames: { search: "find_notes" },
      sanitized: [{ action: "search", requested: "find notes!", applied: "find_notes" }],
    });

    mount();
    await screen.findByText(/vault tool names/i);

    fireEvent.change(screen.getByPlaceholderText("search"), {
      target: { value: "find notes!" },
    });
    listVaultsSpy.mockResolvedValue([
      { ...WORK_VAULT_IDENTITY, tool_renames: { search: "find_notes" } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /save renames/i }));

    expect(await screen.findByText(/was not a valid tool name/i)).toBeInTheDocument();
  });
});

/**
 * SPEC-305 acceptance criterion: "jargon lint on the screen's copy; Lume
 * tokens only" — same scoping as `Automations.test.tsx`/`Exposure.test.tsx`'s
 * own lints: headings, buttons, badges, options, and field labels never
 * carry a protocol name, acronym, or implementation word.
 */
describe("ToolProfiles screen copy — no jargon in the surface (system.md §3 rule 0)", () => {
  const BANNED = [
    /\bjson\b/i,
    /\basgi\b/i,
    /\brest\b/i,
    /\burl\b/i,
    /\bapi\b/i,
    /\bhttp\b/i,
    /\bnamespace\b/i,
    /\bfastmcp\b/i,
    /\bmcp\b/i,
  ];

  it("no heading, button, badge, option, or field label uses an implementation word", async () => {
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([WORK_VAULT_IDENTITY]);
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK_VAULT]);
    vi.spyOn(api, "listGatewayUpstreams").mockResolvedValue([FETCH_UPSTREAM]);
    vi.spyOn(api, "listGatewayProfileTools").mockResolvedValue(WORK_TOOLS);

    mount();
    await screen.findByText("default");
    fireEvent.click(screen.getByRole("button", { name: /^edit$/i }));
    await screen.findByText("work_memory_search");

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("option"),
      ...Array.from(
        document.querySelectorAll(".badge, .card__title, .card__subject, .field__label"),
      ),
    ];

    expect(controls.length).toBeGreaterThan(5);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
