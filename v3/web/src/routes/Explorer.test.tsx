import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { Explorer } from "./Explorer";

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
});
