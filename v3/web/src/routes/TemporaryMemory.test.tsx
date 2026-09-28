import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { NoteSummary, VaultSummary } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { NewTemporaryMemory, TemporaryMemoryBanner } from "./TemporaryMemory";

const NOW = Date.parse("2026-09-28T12:00:00Z");

const WORK: VaultSummary = {
  key: "work",
  purpose: "Everyday notes",
  path: "/data/vaults/work",
  writable: true,
  note_count: 3,
};

const TRIP: VaultSummary = {
  key: "trip",
  purpose: "Research for the Lisbon trip",
  path: "/data/vaults/trip",
  writable: true,
  note_count: 2,
  ephemeral: true,
  expires: "2026-10-12T00:00:00Z",
};

function note(permalink: string, title: string): NoteSummary {
  return {
    permalink,
    title,
    type: "note",
    tags: [],
    folder: "findings",
    modified: "",
    status: "",
    capture_id: "",
  };
}

const NOTES: NoteSummary[] = [
  note("findings/hotels", "Hotels"),
  note("findings/transport", "Transport"),
];

function banner(vault: VaultSummary = TRIP, handlers: { onClosed?: () => void; onPromoted?: () => void } = {}) {
  return render(
    <ToastProvider>
      <TemporaryMemoryBanner
        vault={vault}
        vaults={[WORK, vault]}
        notes={NOTES}
        onClosed={handlers.onClosed ?? (() => {})}
        onPromoted={handlers.onPromoted ?? (() => {})}
        now={NOW}
      />
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NewTemporaryMemory (issue 168)", () => {
  it("creates a temporary memory with a due date", async () => {
    const create = vi.spyOn(api, "createVault").mockResolvedValue(TRIP);
    const onCreated = vi.fn();
    render(
      <ToastProvider>
        <NewTemporaryMemory onCreated={onCreated} onCancel={() => {}} />
      </ToastProvider>,
    );

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "trip" } });
    fireEvent.change(screen.getByLabelText("What it is for"), {
      target: { value: "Research for the Lisbon trip" },
    });
    fireEvent.change(screen.getByLabelText("Due in (days)"), { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        key: "trip",
        purpose: "Research for the Lisbon trip",
        ephemeral: true,
        ttl_days: 14,
      }),
    );
    expect(onCreated).toHaveBeenCalledWith("trip");
  });

  it("shows the hub's reason when the name is refused", async () => {
    vi.spyOn(api, "createVault").mockRejectedValue(
      new ApiError("/api/vaults", 400, { detail: "vault 'trip' is already registered" }),
    );
    render(
      <ToastProvider>
        <NewTemporaryMemory onCreated={() => {}} onCancel={() => {}} />
      </ToastProvider>,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "trip" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(/already registered/)).toBeInTheDocument();
  });
});

describe("TemporaryMemoryBanner (issue 168)", () => {
  it("says when the memory is due", () => {
    banner();
    const box = screen.getByTestId("temporary-memory");
    expect(box).toHaveTextContent("This is a temporary memory.");
    expect(box).toHaveTextContent(/It is due on/);
  });

  it("says when it is overdue", () => {
    banner({ ...TRIP, expires: "2026-09-01T00:00:00Z" });
    expect(screen.getByTestId("temporary-memory")).toHaveTextContent(
      "This temporary memory is overdue.",
    );
  });

  it("copies the chosen notes into an everyday memory", async () => {
    const promote = vi.spyOn(api, "promoteNotes").mockResolvedValue({
      source: "trip",
      target: "work",
      promoted: [{ source: "findings/hotels", permalink: "findings/hotels", path: "findings/hotels.md" }],
    });
    const onPromoted = vi.fn();
    banner(TRIP, { onPromoted });

    fireEvent.click(screen.getByRole("button", { name: "Keep notes…" }));
    const panel = screen.getByTestId("keep-notes");
    // Only everyday memories are offered as the destination.
    expect(within(panel).getByLabelText("Copy into")).toHaveValue("work");
    fireEvent.click(within(panel).getByLabelText(/Hotels/));
    fireEvent.click(within(panel).getByRole("button", { name: "Copy 1 note into work" }));

    await waitFor(() =>
      expect(promote).toHaveBeenCalledWith("trip", { target: "work", notes: ["findings/hotels"] }),
    );
    expect(onPromoted).toHaveBeenCalled();
  });

  it("shows which note already exists when nothing could be copied", async () => {
    vi.spyOn(api, "promoteNotes").mockRejectedValue(
      new ApiError("/api/vaults/trip/promote", 409, {
        detail: "'findings/hotels' already exists in work; nothing was copied.",
      }),
    );
    banner();
    fireEvent.click(screen.getByRole("button", { name: "Keep notes…" }));
    const panel = screen.getByTestId("keep-notes");
    fireEvent.click(within(panel).getByLabelText(/Hotels/));
    fireEvent.click(within(panel).getByRole("button", { name: "Copy 1 note into work" }));

    expect(await screen.findByText(/already exists in work/)).toBeInTheDocument();
  });

  it("closes only once the name is typed", async () => {
    const close = vi
      .spyOn(api, "closeVault")
      .mockResolvedValue({ key: "trip", archived_to: "/data/archive/vaults/trip" });
    const onClosed = vi.fn();
    banner(TRIP, { onClosed });

    fireEvent.click(screen.getByRole("button", { name: "Close…" }));
    const panel = screen.getByTestId("close-memory");
    const button = within(panel).getByRole("button", { name: "Close trip" });
    expect(button).toBeDisabled();
    fireEvent.change(within(panel).getByLabelText("Type trip to confirm"), {
      target: { value: "trip" },
    });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(close).toHaveBeenCalledWith("trip", "trip"));
    expect(onClosed).toHaveBeenCalled();
  });
});
