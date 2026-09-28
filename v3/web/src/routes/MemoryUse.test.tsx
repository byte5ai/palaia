import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ClientUsage } from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import { MemoryUseCard } from "./MemoryUse";

function usage(overrides: Partial<ClientUsage>): ClientUsage {
  return {
    client_id: "t1",
    name: "Claude Code CLI",
    profile: "default",
    revoked: false,
    lookups: 0,
    saves: 0,
    sessions: 0,
    sessions_saved_first: 0,
    days: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MemoryUseCard (issue 524)", () => {
  it("shows lookups, saves and sessions that saved before looking", async () => {
    vi.spyOn(api, "tokenUsage").mockResolvedValue([
      usage({ lookups: 12, saves: 5, sessions: 4, sessions_saved_first: 1 }),
    ]);

    render(<MemoryUseCard />);

    const row = await screen.findByTestId("memory-use-t1");
    expect(row).toHaveTextContent("Claude Code CLI");
    expect(row).toHaveTextContent("12 lookups · 5 saves");
    expect(row).toHaveTextContent("1 of 4 sessions saved before looking anything up.");
  });

  it("flags a client that saves without ever looking anything up", async () => {
    vi.spyOn(api, "tokenUsage").mockResolvedValue([
      usage({ lookups: 0, saves: 3, sessions: 2, sessions_saved_first: 2 }),
    ]);

    render(<MemoryUseCard />);

    expect(
      await screen.findByText("It saves without ever looking anything up first."),
    ).toBeInTheDocument();
  });

  it("names a connection without a palaia token as such", async () => {
    vi.spyOn(api, "tokenUsage").mockResolvedValue([
      usage({ client_id: "oauth", name: null, lookups: 1 }),
    ]);

    render(<MemoryUseCard />);

    expect(await screen.findByTestId("memory-use-oauth")).toHaveTextContent(
      "Connection without a palaia token",
    );
  });

  it("says so when nothing was used", async () => {
    vi.spyOn(api, "tokenUsage").mockResolvedValue([]);

    render(<MemoryUseCard />);

    expect(await screen.findByText(/No AI tool has looked anything up/)).toBeInTheDocument();
  });

  it("hides itself on a hub that does not count", async () => {
    vi.spyOn(api, "tokenUsage").mockRejectedValue(
      new ApiError("/api/auth/tokens/usage", 404, { detail: "Not Found" }),
    );

    const { container } = render(<MemoryUseCard />);

    await vi.waitFor(() => expect(api.tokenUsage).toHaveBeenCalled());
    expect(container.querySelector("[data-testid='memory-use']")).toBeNull();
  });
});
