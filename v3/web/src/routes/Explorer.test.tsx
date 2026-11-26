import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { NoteSummary, TokenInfo, VaultSummary } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { Explorer } from "./Explorer";

const WORK: VaultSummary = {
  key: "work",
  purpose: "Work notes.",
  path: "/x",
  writable: true,
  note_count: 2,
};

const A_TOKEN: TokenInfo = {
  id: "t1",
  name: "Claude Code CLI",
  profile: "default",
  scopes: [],
  created_at: "2026-09-01T00:00:00Z",
  revoked_at: null,
  last_used_at: null,
};

function note(permalink: string, title: string, folder: string): NoteSummary {
  return {
    permalink,
    title,
    type: "note",
    tags: [],
    folder,
    modified: "2026-09-01",
    status: "",
    capture_id: "",
  };
}

const NO_INBOX = {
  count: 0,
  oldest_capture_id: null,
  oldest_age_seconds: null,
  last_capture_id: null,
  last_captured_at: null,
};

function mount() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Explorer />
      </ToastProvider>
    </MemoryRouter>,
  );
}

function stubVault(vault: VaultSummary = WORK, notes: NoteSummary[] = [note("projects/api", "API Gateway", "projects")]) {
  vi.spyOn(api, "listVaults").mockResolvedValue([vault]);
  vi.spyOn(api, "listNotes").mockResolvedValue(notes);
  vi.spyOn(api, "inboxStatus").mockResolvedValue(NO_INBOX);
  vi.spyOn(api, "listTokens").mockResolvedValue([A_TOKEN]);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("a link to one note (the command palette)", () => {
  const HOME: VaultSummary = { ...WORK, key: "home", path: "/y" };

  function Jump() {
    const navigate = useNavigate();
    return (
      <button type="button" onClick={() => navigate("/memories?memory=work&note=projects/api")}>
        jump
      </button>
    );
  }

  function stubTwo() {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK, HOME]);
    vi.spyOn(api, "listNotes").mockImplementation(async (key) =>
      key === "home"
        ? [note("money/tax", "Tax", "money")]
        : [note("projects/api", "API Gateway", "projects"), note("projects/db", "Database", "projects")],
    );
    vi.spyOn(api, "inboxStatus").mockResolvedValue(NO_INBOX);
    vi.spyOn(api, "listTokens").mockResolvedValue([A_TOKEN]);
    vi.spyOn(api, "noteGraph").mockResolvedValue({ outbound: [], inbound: [] });
    vi.spyOn(api, "noteHistory").mockResolvedValue([]);
    return vi
      .spyOn(api, "readNote")
      .mockImplementation(async (_key, permalink) => ({ ...note(permalink, permalink, ""), body: "", created: "" }));
  }

  it("opens that memory and that note, not the first memory", async () => {
    const read = stubTwo();
    render(
      <MemoryRouter initialEntries={["/memories?memory=home&note=money/tax"]}>
        <ToastProvider>
          <Explorer />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("combobox", { name: "Memory" })).toHaveValue("home");
    await waitFor(() => expect(read).toHaveBeenCalledWith("home", "money/tax"));
    expect(await screen.findByRole("button", { name: "Tax" })).toHaveAttribute("aria-current", "true");
  });

  it("follows the same link again after the reader moved on", async () => {
    stubTwo();
    render(
      <MemoryRouter initialEntries={["/memories?memory=work&note=projects/api"]}>
        <ToastProvider>
          <Jump />
          <Explorer />
        </ToastProvider>
      </MemoryRouter>,
    );
    const api_note = await screen.findByRole("button", { name: "API Gateway" });
    expect(api_note).toHaveAttribute("aria-current", "true");

    fireEvent.click(screen.getByRole("button", { name: "Database" }));
    expect(screen.getByRole("button", { name: "API Gateway" })).not.toHaveAttribute("aria-current");
    fireEvent.click(screen.getByRole("button", { name: "jump" }));

    expect(screen.getByRole("button", { name: "API Gateway" })).toHaveAttribute("aria-current", "true");
  });
});

describe("Memories › Browse: loading, error and empty are different states (report §5.7)", () => {
  it("a failed listing is an error with Try again — never 'No memories yet'", async () => {
    const list = vi
      .spyOn(api, "listVaults")
      .mockRejectedValue(new ApiError("/api/vaults", 500, { detail: "the index is locked" }));

    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load your memories");
    expect(screen.getByText("the index is locked")).toBeInTheDocument();
    expect(screen.queryByText(/no memories yet/i)).not.toBeInTheDocument();

    list.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("No memories yet")).toBeInTheDocument();
  });

  it("an empty list offers to create the first memory, with the hub's name rule", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([]);
    const create = vi.spyOn(api, "createVault").mockResolvedValue({ ...WORK, note_count: 0 });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Create memory" }));

    const dialog = screen.getByRole("dialog", { name: "New memory" });
    expect(dialog).toHaveTextContent("Optional");
    const submit = within(dialog).getByRole("button", { name: "Create memory" });

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Work Notes" } });
    expect(screen.getByText(/use lowercase letters, numbers and dashes/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "work" } });
    fireEvent.change(screen.getByLabelText(/what it's for/i), {
      target: { value: "Projects and decisions" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        key: "work",
        purpose: "Projects and decisions",
        path: undefined,
      }),
    );
  });
});

describe("Memories › Browse", () => {
  it("lists notes waiting to be filed first, as 'To file' (issue 375)", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listNotes").mockResolvedValue([
      note("projects/api", "API Gateway", "projects"),
      note("inbox/2026-09-01-capture", "A fresh capture", "inbox"),
    ]);
    vi.spyOn(api, "inboxStatus").mockResolvedValue({ ...NO_INBOX, count: 1 });
    vi.spyOn(api, "listTokens").mockResolvedValue([A_TOKEN]);

    mount();

    const rows = await screen.findAllByRole("button", { name: /a fresh capture|api gateway/i });
    expect(rows[0]).toHaveTextContent("A fresh capture");
    const pill = screen.getByText("1 to file");
    expect(pill.closest(".pill")).toHaveAttribute("title", "Captured notes waiting to be sorted");
    expect(screen.getByText("To file")).toBeInTheDocument();
    expect(screen.queryByText(/uncurated/i)).not.toBeInTheDocument();
  });

  it("says when a note or its links cannot be loaded instead of a skeleton forever (issue 378)", async () => {
    stubVault();
    vi.spyOn(api, "readNote").mockRejectedValue(
      new ApiError("/api/vaults/work/notes/projects/api", 500, { detail: "the disk is on fire" }),
    );
    vi.spyOn(api, "noteGraph").mockRejectedValue(new Error("offline"));
    vi.spyOn(api, "noteHistory").mockResolvedValue([]);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /api gateway/i }));

    expect(await screen.findByText("Couldn't load this note.")).toBeInTheDocument();
    expect(screen.getByText("the disk is on fire")).toBeInTheDocument();
    expect(await screen.findByText(/couldn't load the links/i)).toBeInTheDocument();
  });

  it("shows a captured note as its text and three plain facts, without tags or the hash", async () => {
    stubVault();
    vi.spyOn(api, "readNote").mockResolvedValue({
      ...note("projects/api", "API Gateway", "projects"),
      type: "capture",
      body:
        "Changes who to ask\n\n- [entity] Billing service\n- [why] Changes who to ask\n" +
        "- [raw] The payments team owns billing from December.\n- [source] chat\n" +
        "- [capture_hash] e2432368920442cb\n",
      created: "2026-10-20T09:00:00Z",
    });
    vi.spyOn(api, "noteGraph").mockResolvedValue({ outbound: [], inbound: [] });
    vi.spyOn(api, "noteHistory").mockResolvedValue([]);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /api gateway/i }));

    expect(await screen.findByText("The payments team owns billing from December.")).toBeInTheDocument();
    expect(screen.getByText("About").nextElementSibling).toHaveTextContent("Billing service");
    expect(screen.getByText("Why it was kept").nextElementSibling).toHaveTextContent("Changes who to ask");
    expect(screen.getByText("From").nextElementSibling).toHaveTextContent("chat");
    expect(screen.queryByText(/\[entity\]|\[raw\]|capture_hash|e2432368920442cb/)).not.toBeInTheDocument();
  });

  it("shows history as who saved it and when, with the commit only in the tooltip", async () => {
    stubVault();
    vi.spyOn(api, "readNote").mockResolvedValue({
      ...note("projects/api", "API Gateway", "projects"),
      modified: "2026-10-23T13:35:17Z",
      body: "The gateway routes every request.",
      created: "2026-10-20T09:00:00Z",
    });
    vi.spyOn(api, "noteGraph").mockResolvedValue({ outbound: [], inbound: [] });
    vi.spyOn(api, "noteHistory").mockResolvedValue([
      {
        sha: "93e8393abcdef",
        subject: "-/-/engine: write projects/api",
        author_name: "Claude Code CLI",
        committed_at: "2026-10-23T13:35:17Z",
      },
      {
        sha: "11aa22bb33cc",
        subject: "-/-/dashboard: edit projects/api",
        author_name: "human",
        committed_at: "2026-10-23T14:00:00Z",
      },
    ]);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /api gateway/i }));

    const created = await screen.findByText(/^Created by Claude Code CLI · /);
    expect(created).toHaveAttribute("title", expect.stringContaining("93e8393"));
    expect(screen.getByText(/^Edited by you · /)).toBeInTheDocument();
    expect(screen.queryByText(/engine: write/)).not.toBeInTheDocument();
    expect(screen.getByText(/^Updated /)).toHaveAttribute("title");
    expect(screen.queryByText(/2026-10-23T13:35:17Z/)).not.toBeInTheDocument();
  });

  it("shows a generated description as missing, and offers to connect an AI app only when none is", async () => {
    stubVault({ ...WORK, purpose: "palaia vault 'work'." });
    vi.spyOn(api, "listTokens").mockResolvedValue([]);

    mount();

    expect(await screen.findByText("No description yet.")).toBeInTheDocument();
    expect(screen.queryByText("palaia vault 'work'.")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Connect an AI app" })).toHaveAttribute(
      "href",
      "/apps",
    );
  });

  it("an empty memory says how it fills, with the one step that starts it", async () => {
    stubVault(WORK, []);
    vi.spyOn(api, "listTokens").mockResolvedValue([]);

    mount();

    expect(await screen.findByRole("heading", { name: "No notes in work yet" })).toBeInTheDocument();
    expect(screen.queryByText("Pick a note from the list, or search.")).not.toBeInTheDocument();
    // One filled button, not a second one in the side pane.
    const links = await screen.findAllByRole("link", { name: "Connect an AI app" });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveClass("btn--primary");
  });

  it("an empty memory with an AI app connected offers nothing to click", async () => {
    stubVault(WORK, []);

    mount();

    expect(await screen.findByRole("heading", { name: "No notes in work yet" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connect an AI app" })).not.toBeInTheDocument();
  });

  it("does not suggest connecting an AI app when one is", async () => {
    stubVault();

    mount();

    expect(await screen.findByText("Work notes.")).toBeInTheDocument();
    await waitFor(() => expect(api.listTokens).toHaveBeenCalled());
    expect(screen.queryByRole("link", { name: /connect an ai app/i })).not.toBeInTheDocument();
  });
});

describe("Memories › Browse › Advanced: tool names (report §3.7)", () => {
  it("renames a memory's tools and shows what the hub actually saved", async () => {
    stubVault();
    vi.spyOn(api, "listGatewayVaults").mockResolvedValue([
      { key: "work", name: "work", purpose: "", tool_renames: {}, namespace: "work_memory", sanitized: [] },
    ]);
    const update = vi.spyOn(api, "updateGatewayVault").mockResolvedValue({
      key: "work",
      name: "work",
      purpose: "",
      tool_renames: { search: "find_it" },
      namespace: "work_memory",
      sanitized: [{ action: "search", requested: "find it", applied: "find_it" }],
    });

    mount();
    fireEvent.click(await screen.findByText("Advanced: tool names for work"));
    expect(screen.getByText(/apps may ask you to approve renamed tools again/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New name for search"), { target: { value: "find it" } });
    expect(screen.getByText("work_memory_find_it")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save tool names" }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith("work", { tool_renames: { search: "find it" } }),
    );
    expect(await screen.findByText(/isn't a valid tool name, so palaia saved "find_it"/)).toBeInTheDocument();
  });
});

describe("memory search (issue 384)", () => {
  it("searches once typing pauses, with the final text, not once per keystroke", async () => {
    stubVault();
    const search = vi.spyOn(api, "search").mockResolvedValue([]);

    mount();
    const box = await screen.findByLabelText(/search this memory/i);
    fireEvent.change(box, { target: { value: "a" } });
    fireEvent.change(box, { target: { value: "ab" } });
    fireEvent.change(box, { target: { value: "abc" } });

    expect(await screen.findByText("0 results")).toBeInTheDocument();
    expect(search.mock.calls.map((call) => call[1])).toEqual(["abc"]);
    expect(search.mock.calls[0]![2]).toBeInstanceOf(AbortSignal);

    // Clearing the box drops the results at once, with no request.
    fireEvent.change(box, { target: { value: "" } });
    expect(screen.queryByText("0 results")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(search).toHaveBeenCalledTimes(1);
  });
});
