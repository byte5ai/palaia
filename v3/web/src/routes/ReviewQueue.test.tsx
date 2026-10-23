import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { ProposalSummary, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import { ReviewQueue } from "./ReviewQueue";

const WORK: VaultSummary = {
  key: "work",
  purpose: "Work notes.",
  path: "/x",
  writable: true,
  note_count: 4,
};

const MERGE: ProposalSummary = {
  permalink: "review/merge-api-notes",
  title: "Merge the two API gateway notes",
  status: "pending",
  created: "2026-09-01",
  body: "Both notes describe the same gateway; keep projects/api-gateway.",
};

function mount() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <ReviewQueue />
      </ToastProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Memories › Needs review (issue 375)", () => {
  it("lists every vault's pending proposals and takes the decision", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listReviewQueue").mockResolvedValue({ proposals: [MERGE], decide_tool: "" });
    const decide = vi
      .spyOn(api, "decideReview")
      .mockResolvedValue({ permalink: MERGE.permalink, status: "approved" });

    mount();

    expect(await screen.findByText(MERGE.title)).toBeInTheDocument();
    expect(screen.getByText("1 proposal waiting. Nothing changes until you decide.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText(/keep projects\/api-gateway/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));

    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("work", MERGE.permalink, "approved"),
    );
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
  });

  it("explains an empty queue", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listReviewQueue").mockResolvedValue({ proposals: [], decide_tool: "" });

    mount();

    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
    expect(
      screen.getByText(/palaia asks you here before it merges, renames or archives a note/i),
    ).toBeInTheDocument();
  });

  it("says when the queue cannot be loaded and offers a retry", async () => {
    const vaults = vi.spyOn(api, "listVaults").mockRejectedValue(new Error("offline"));

    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load what needs review");
    // An error is never shown as an empty queue.
    expect(screen.queryByText("Nothing to review")).not.toBeInTheDocument();
    vaults.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Nothing to review")).toBeInTheDocument();
  });
});
