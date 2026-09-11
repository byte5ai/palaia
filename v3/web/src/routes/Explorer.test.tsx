import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NoteSummary, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { Explorer } from "./Explorer";

const WORK: VaultSummary = {
  key: "work",
  purpose: "Work notes.",
  path: "/x",
  writable: true,
  note_count: 2,
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

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Explorer", () => {
  it("teaches the next action when no vault exists yet — never a dead end", async () => {
    render(
      <MemoryRouter>
        <Explorer />
      </MemoryRouter>,
    );

    // No hub is actually running in this test, so /api/vaults fails and
    // the empty-vaults path renders — the same path a fresh install with
    // zero vaults takes before the wizard's third step runs.
    expect(await screen.findByText(/no vault exists yet/i)).toBeInTheDocument();
    // ...and the action is one click away, not a name to go looking for (issue 372).
    expect(screen.getByRole("link", { name: /setup wizard/i })).toHaveAttribute(
      "href",
      "/onboarding",
    );
  });

  it("shows waiting captures in the tree, first, instead of a dead 'uncurated' link (issue 375)", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listNotes").mockResolvedValue([
      note("projects/api", "API Gateway", "projects"),
      note("inbox/2026-09-01-capture", "A fresh capture", "inbox"),
    ]);
    vi.spyOn(api, "inboxStatus").mockResolvedValue({
      count: 1,
      oldest_capture_id: "c1",
      oldest_age_seconds: 30,
      last_capture_id: "c1",
      last_captured_at: "2026-09-01",
    });

    render(
      <MemoryRouter>
        <Explorer />
      </MemoryRouter>,
    );

    const rows = await screen.findAllByRole("button", { name: /a fresh capture|api gateway/i });
    expect(rows[0]).toHaveTextContent("A fresh capture");
    const badge = screen.getByText(/1 uncurated/i);
    expect(badge.closest("a")).toBeNull();
  });
});
