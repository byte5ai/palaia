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

describe("Review queue (issue 375)", () => {
  it("lists every vault's pending proposals and takes the decision", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listReviewQueue").mockResolvedValue({ proposals: [MERGE], decide_tool: "" });
    const decide = vi
      .spyOn(api, "decideReview")
      .mockResolvedValue({ permalink: MERGE.permalink, status: "approved" });

    mount();

    expect(await screen.findByText(MERGE.title)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show details/i }));
    expect(screen.getByText(/keep projects\/api-gateway/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));

    await waitFor(() =>
      expect(decide).toHaveBeenCalledWith("work", MERGE.permalink, "approved"),
    );
    expect(await screen.findByText(/nothing waiting for you/i)).toBeInTheDocument();
  });

  it("explains an empty queue", async () => {
    vi.spyOn(api, "listVaults").mockResolvedValue([WORK]);
    vi.spyOn(api, "listReviewQueue").mockResolvedValue({ proposals: [], decide_tool: "" });

    mount();

    expect(await screen.findByText(/nothing waiting for you/i)).toBeInTheDocument();
  });

  it("says when the queue cannot be loaded and offers a retry", async () => {
    const vaults = vi.spyOn(api, "listVaults").mockRejectedValue(new Error("offline"));

    mount();

    expect(await screen.findByText(/could not load the review queue/i)).toBeInTheDocument();
    vaults.mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/nothing waiting for you/i)).toBeInTheDocument();
  });
});
